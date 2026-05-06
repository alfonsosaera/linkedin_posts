# Buffer API Integration - Implementation Summary

## What Was Added

Direct integration with Buffer's GraphQL API to schedule LinkedIn posts with first comments, replacing the CSV export workflow for real-time posting.

## Key Changes to `src/post_creator.py`

### New Buffer API Section (~175 lines)

**Constants:**
- `BUFFER_API_URL` — API endpoint
- `CREATE_LINKEDIN_POST` — GraphQL mutation for post creation
- `QUERY_ORGANIZATIONS` — Discover org
- `QUERY_CHANNELS` — Discover LinkedIn channel

**Functions:**

1. **`run_buffer_query(query, variables) → dict`**
   - Executes GraphQL queries against Buffer API
   - Reads `BUFFER_API_KEY` from `.env`
   - Handles authentication via Bearer token
   - Raises clear errors if key is missing or API returns errors

2. **`get_linkedin_channel_id() → str`**
   - Auto-discovers your first LinkedIn channel
   - Queries organizations, then channels
   - Returns the channel ID needed for post scheduling

3. **`parse_post_for_buffer(text) → (body, first_comment, paper_url)`**
   - Splits post at marker: `"👉 Follow my blog for more https://lovednacodeblog.com/"`
   - Body = everything before marker (sent as post text)
   - First comment = everything after (links block, sent as first Buffer comment)
   - Paper URL = first https:// URL in first comment (for link attachment)

4. **`upload_to_buffer(input_dir, start_date, schedule_path)`**
   - Main workflow: reads `.txt` files and schedules them in Buffer
   - Uses same schedule CSV as the CSV export step
   - Converts time slots to ISO8601 format
   - Handles image URL extraction from `.images.json` (for logging, not sent to API)
   - Prints per-post status with Buffer post IDs

### New CLI Commands

**New `buffer` subcommand:**
```bash
uv run python src/post_creator.py buffer \
  --input input/ \
  --start-date 2026-05-10 \
  [--schedule /path/to/schedule.csv]
```

**New `--buffer` flag on existing `all` command:**
```bash
uv run python src/post_creator.py all \
  --input input/ \
  --start-date 2026-05-10 \
  [--no-upload] [--force] [--schedule /path] \
  [--buffer]  # ← new flag
```

When `--buffer` is set, the full workflow (generate → csv → buffer upload) runs in sequence.

## Setup Required

Add to your `.env` file:
```
BUFFER_API_KEY=your_buffer_api_key_here
```

## Post Format

The implementation expects `.txt` files with this structure:

```
[post body with title, intro, findings, conclusions, limitations]

👉 Follow my blog for more https://lovednacodeblog.com/

[links block - everything after this line becomes the first comment]
📚 Journal Name paper: https://doi.org/...
💻 Code: https://github.com/...
🔗 Website: https://...
```

**Critical:** The blog URL marker is the split point. Everything after it is sent as the first Buffer comment.

## Workflow

When you run `buffer` or `all --buffer`:

1. **Discover Channel**
   - Query Buffer organizations
   - Get first org ID
   - Query channels for that org
   - Filter for LinkedIn service
   - Use first LinkedIn channel ID

2. **Load Schedule**
   - Read `posting_schedule.csv` (weekday → time mappings)
   - Generate datetime slots starting from `--start-date`
   - Alphabetically sort `.txt` files (case-insensitive)

3. **For Each Post**
   - Parse post → body + first_comment + paper_url
   - Get next scheduled datetime slot
   - Convert to ISO8601 format
   - Query for image URL from `.images.json` (optional, logged only)
   - Execute `CreateLinkedInPost` mutation
   - Log result with post ID or error

4. **Output**
   ```
   Discovering LinkedIn channel in Buffer...
   Using channel ID: ch_abc123
   Found 5 LinkedIn post(s).

   ✓ paper1.txt → scheduled for 2026-05-12 09:00 (ID: post_123)
   ✓ paper2.txt → scheduled for 2026-05-14 10:30 (ID: post_124)
   ...
   Done uploading to Buffer.
   ```

## Error Handling

- **Missing `BUFFER_API_KEY`:** Clear error directing user to `.env`
- **No Buffer organizations:** RuntimeError with description
- **No LinkedIn channels:** RuntimeError listing which org was checked
- **GraphQL errors:** RuntimeError with API error details
- **Individual post failures:** Logged per-post, doesn't stop the batch

## Testing

The implementation was tested with:
- Existing `.txt` posts from the repository
- Parsing logic verified against real post format
- CLI help shows all new commands and flags
- Syntax validation passes

## Files Modified

- **`src/post_creator.py`** — added Buffer API section + CLI commands
- **`BUFFER_API.md`** — new documentation with usage examples
- **`IMPLEMENTATION_SUMMARY.md`** — this file

## Files Not Modified

- `.env` — user must add `BUFFER_API_KEY` manually
- Templates and schedules — reused as-is
- Checker system — unchanged
- CSV export — still works independently

## Integration with Existing Workflow

```
PDF → Extract & Generate → LinkedIn Posts (.txt)
                              ↓
                    Image Processing (Imgur)
                              ↓
                        CSV Export (unchanged)
                              ↓
                    [NEW] Buffer API Upload
```

The CSV export and Buffer API upload are independent. You can:
- Use CSV only (current behavior)
- Use Buffer API only (new)
- Use both (for redundancy or different scheduling)

## Documentation

- **BUFFER_API.md** — Complete user guide with examples and troubleshooting
- **CLAUDE.md** — Architecture remains unchanged, now references the Buffer API feature
- **README.md** — Update the commands section to mention `buffer` and `all --buffer`

## Future Enhancements

1. **Image Attachment Support** — If Buffer adds image attachment to GraphQL
2. **Batch Scheduling** — Support scheduling multiple posts in a single API call
3. **Configuration** — Allow custom first comment format via template
4. **Retry Logic** — Automatic retry on transient API failures
5. **Metrics** — Track scheduled post counts, error rates, timing

## Quick Start

1. **Add API key to `.env`:**
   ```
   BUFFER_API_KEY=your_key_here
   ```

2. **Upload existing posts:**
   ```bash
   uv run python src/post_creator.py buffer \
     --input input/my_posts \
     --start-date 2026-05-10
   ```

3. **Or run full workflow:**
   ```bash
   uv run python src/post_creator.py all \
     --input input/ \
     --start-date 2026-05-10 \
     --buffer
   ```

See `BUFFER_API.md` for full documentation.
