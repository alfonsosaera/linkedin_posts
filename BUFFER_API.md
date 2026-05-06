# Buffer API Integration

This document explains how to use the new Buffer GraphQL API feature to upload LinkedIn posts directly to Buffer with automatic scheduling.

## Overview

The Buffer API integration adds two new commands:

1. **`buffer` subcommand** — Upload existing `.txt` posts directly to Buffer
2. **`all --buffer` flag** — Run the full workflow (PDF → posts → CSV → Buffer upload) in one command

## Prerequisites

1. **Buffer GraphQL API Access**
   - You must have a Buffer account with LinkedIn integration
   - API access requires an API key

2. **Set up the API Key**
   - Get your API key from the Buffer dashboard
   - Add it to your `.env` file:
     ```
     BUFFER_API_KEY=your_actual_key_here
     ```
   - The application reads this with `load_dotenv()` at startup

## How It Works

### Post Parsing

LinkedIn posts are split at a specific marker. Everything before and including the blog URL line becomes the **post body**, and everything after (the links block) becomes the **first comment**:

```
[POST BODY]
👉 Follow my blog for more https://lovednacodeblog.com/

[LINKS BLOCK → becomes first comment in Buffer]
📚 Bioinformatics paper: https://doi.org/10.1093/bioinformatics/btag023
💻 Code: https://github.com/HorvathLab/scSNViz
🔗 Website: https://example.com
```

### Scheduling

Posts are scheduled using the same `posting_schedule.csv` mechanism as the CSV export:

1. Load the posting schedule (weekday → time mappings)
2. Generate time slots starting from `--start-date`
3. Assign one slot per post (alphabetically sorted)
4. Convert to ISO8601 format for the Buffer API

### Buffer API Calls

1. **Discover your LinkedIn channel:**
   - Query organizations → get org ID
   - Query channels with org ID → filter for LinkedIn service
   - Use the first LinkedIn channel's ID

2. **Schedule each post:**
   - Send `CreateLinkedInPost` mutation with:
     - `body` — the post text (before blog URL)
     - `firstComment` — the links block
     - `url` — paper URL extracted from the links block
     - `scheduledAt` — ISO8601 timestamp from schedule
   - Receive post ID and confirmation

## Usage

### Option 1: Upload Existing Posts Standalone

If you already have `.txt` posts and want to upload them to Buffer:

```bash
uv run python src/post_creator.py buffer \
  --input input/my_posts \
  --start-date 2026-05-10
```

Example output:
```
Discovering LinkedIn channel in Buffer...
Using channel ID: ch_123abc
Found 5 LinkedIn post(s).

✓ paper1.txt → scheduled for 2026-05-12 09:00 (ID: post_123)
✓ paper2.txt → scheduled for 2026-05-14 10:30 (ID: post_124)
✓ paper3.txt → scheduled for 2026-05-15 09:00 (ID: post_125)
✓ paper4.txt → scheduled for 2026-05-16 10:30 (ID: post_126)
✓ paper5.txt → scheduled for 2026-05-17 09:00 (ID: post_127)

Done uploading to Buffer.
```

### Option 2: Full Workflow (PDF → Buffer)

Generate posts from PDFs and immediately upload to Buffer:

```bash
uv run python src/post_creator.py all \
  --input input/ \
  --start-date 2026-05-10 \
  --buffer
```

This runs:
1. Extract data from PDFs and generate LinkedIn posts
2. Extract images and upload to Imgur
3. Generate Buffer CSV (for reference)
4. Upload posts directly to Buffer via API

### Custom Posting Schedule

Use a different schedule CSV file:

```bash
uv run python src/post_creator.py buffer \
  --input input/posts \
  --start-date 2026-05-10 \
  --schedule /path/to/my_schedule.csv
```

## Troubleshooting

### Missing API Key

**Error:** `ValueError: BUFFER_API_KEY not found in environment. Please add it to your .env file.`

**Solution:** Add `BUFFER_API_KEY=your_key` to your `.env` file and restart the application.

### No LinkedIn Channels Found

**Error:** `RuntimeError: No LinkedIn channels found in organization 'MyOrg'`

**Causes:**
- LinkedIn integration not set up in Buffer
- No LinkedIn profiles connected to your Buffer account

**Solution:** Set up LinkedIn integration in the Buffer dashboard and try again.

### Post Upload Fails with GraphQL Error

**Error:** `RuntimeError: Buffer API error: [{'message': '...'}]`

**Causes:**
- Invalid post body or first comment formatting
- Scheduled time is in the past
- API key has expired or lacks permissions

**Solution:** Check the error message, verify the `.txt` file format, ensure the scheduled time is in the future.

## Post Structure Reference

Here's the expected structure of a `.txt` LinkedIn post:

```
🔬 Title with Emoji 🚀

The study "...", published in Journal by Authors, introduces ...

📌 Key finding 1
📌 Key finding 2
📌 Key finding 3

✅ Conclusion
⚠️ Limitation

📢 Join the Conversation 📢
Share your ideas...

👉 Follow my blog for more https://lovednacodeblog.com/

📚 Journal Name paper: https://doi.org/...
💻 Code: https://github.com/...
🔗 Website: https://... (optional)
```

**Critical:** The `👉 Follow my blog for more https://lovednacodeblog.com/` line MUST be present to split the post correctly. Everything after it becomes the first comment.

## Implementation Details

### New Constants
- `BUFFER_API_URL` = `"https://api.buffer.com"`
- `CREATE_LINKEDIN_POST` — GraphQL mutation
- `QUERY_ORGANIZATIONS`, `QUERY_CHANNELS` — Discovery queries

### New Functions

**`run_buffer_query(query: str, variables: dict | None = None) -> dict`**
- Executes GraphQL against Buffer API
- Reads `BUFFER_API_KEY` from environment
- Raises clear errors on HTTP or GraphQL errors

**`get_linkedin_channel_id() -> str`**
- Discovers the first LinkedIn channel in your Buffer account
- Called automatically during upload

**`parse_post_for_buffer(text: str) -> tuple[str, str, str]`**
- Splits post text on the blog URL marker
- Extracts paper URL via regex
- Returns: (body, first_comment, paper_url)

**`upload_to_buffer(input_dir: str, start_date: date, schedule_path: str)`**
- Main workflow function
- Reads `.txt` files and `.images.json` files
- Schedules each post via the Buffer API

### CLI Changes

**New `buffer` subcommand:**
```bash
uv run python src/post_creator.py buffer --input DIR --start-date DATE [--schedule PATH]
```

**New `--buffer` flag on `all` subcommand:**
```bash
uv run python src/post_creator.py all --input DIR --start-date DATE [--schedule PATH] [--buffer]
```

## Advanced: Image URLs

The implementation reads image URLs from `.images.json` files (same format as the CSV export step) but does **not** currently send them through the API. This is because:
- Buffer's GraphQL doesn't support direct image URL attachment in the same way as the CSV import
- Images can be added separately in the Buffer dashboard if needed

To add image support in the future, extend the `CREATE_LINKEDIN_POST` mutation to include image attachments if Buffer adds that capability.

## See Also

- Main README: `README.md`
- CLAUDE.md: Architecture and project structure
- Original Buffer example code: See the prompt context in CLAUDE.md
