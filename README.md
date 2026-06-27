# LinkedIn Post Generator

Generate LinkedIn posts from scientific paper PDFs using a two-stage LLM pipeline with automatic image extraction, validation, and direct Buffer API scheduling.

## Features

- **PDF Processing**: Extract structured data from scientific papers (authors, title, journal, key findings)
- **LinkedIn Post Generation**: Create polished, professional posts with proper formatting
- **Image Extraction**: Automatically extract figures from PDFs using PyMuPDF
- **Smart Image Selection**: Use GPT-4o vision to select the most impactful figure
- **imgbb Upload**: Automatically upload images for use in Buffer
- **Buffer CSV Export**: Generate ready-to-upload CSV for Buffer bulk scheduling
- **Buffer API Integration**: Upload posts directly to Buffer with first comments for additional links
- **Validation System**: LLM-based checkers ensure quality output with automatic retry
- **Scheduled Posting**: Assign publication times to each post based on a configurable weekly schedule
- **Alternative Source Support**: Override journal/URL metadata for papers from non-official sources

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/linkedin_posts.git
cd linkedin_posts

# Install dependencies using uv
uv sync
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key
IMGBB_API_KEY=your_imgbb_api_key             # Optional, for image uploads
BUFFER_API_KEY=your_buffer_api_key           # Optional, for Buffer API uploads
BUFFER_CHANNEL_ID=your_channel_id            # Optional, set manually if Buffer API cannot discover it
```

**Get Your Keys:**
- **imgbb API Key**: https://api.imgbb.com/ (free tier includes API access)
- **Buffer API Key**: Available in your Buffer account settings under "Integrations" → "API"
- **Buffer Channel ID**: Found in Buffer dashboard under Settings → Channels → LinkedIn. Only needed if the Buffer API returns a permission error when discovering the channel automatically.

### Posting Schedule

Edit `templates/posting_schedule.csv` to customize when posts are scheduled:

```csv
weekday,time
Sunday,20:53
Monday,17:21
Tuesday,15:47
Wednesday,16:22
Thursday,16:30
Friday,15:11
Saturday,09:21
```

**Rules:**
- Each post gets the next available weekday slot from the schedule
- Weekdays not defined in the schedule are automatically skipped
- Times are in HH:MM 24-hour format
- Use a custom schedule with `--schedule /path/to/custom_schedule.csv`

### Alternative Source Metadata (Optional)

When a PDF is downloaded from an alternative source (e.g., bioRxiv) instead of the official journal, create an optional sidecar JSON file next to the PDF:

**File: `{filename}.meta.json`**

```json
{
  "journal": "Nature Methods",
  "paper_url": "https://doi.org/10.1038/s41592-025-02706-x"
}
```

Both fields are optional. If the sidecar file exists, those values override what the LLM extracts from the PDF text.

Example structure:
```
input/
  ├── paper.pdf
  ├── paper.meta.json        # Optional metadata override
  ├── paper.txt              # Generated output
  ├── paper.json             # Generated output
  └── ...
```

## Usage

### Full Workflow

Process PDFs from generation to Buffer scheduling in one command:

```bash
# With image uploads and Buffer API scheduling
uv run python src/post_creator.py all --input input/ --start-date 2026-05-14 --buffer

# Without image uploads (faster, images extracted locally)
uv run python src/post_creator.py all --input input/ --no-upload --start-date 2026-05-14 --buffer

# With CSV export only (no Buffer API)
uv run python src/post_creator.py all --input input/ --start-date 2026-05-14
```

### Run Steps Independently

```bash
# Step 1: Generate LinkedIn posts from PDFs
uv run python src/post_creator.py generate --input input/

# Step 2: Create Buffer CSV for manual bulk upload
uv run python src/post_creator.py csv --input input/ --start-date 2026-05-14

# Step 3: Upload posts directly to Buffer via API
uv run python src/post_creator.py buffer --input input/ --start-date 2026-05-14
```

### Command Options

```bash
# Generate command
uv run python src/post_creator.py generate \
  --input input/ \
  [--no-upload]              # Skip imgbb upload, extract locally
  [--force]                  # Reprocess PDFs even if outputs exist

# CSV command
uv run python src/post_creator.py csv \
  --input input/ \
  --start-date 2026-05-14 \
  [--schedule /path/to/schedule.csv]

# Buffer command
uv run python src/post_creator.py buffer \
  --input input/ \
  --start-date 2026-05-14 \
  [--schedule /path/to/schedule.csv]

# All command (combines all steps)
uv run python src/post_creator.py all \
  --input input/ \
  --start-date 2026-05-14 \
  [--no-upload] \
  [--force] \
  [--schedule /path/to/schedule.csv] \
  [--buffer]                 # Add to enable Buffer API upload
```

## Buffer API Integration

### Overview

The Buffer API integration allows you to upload LinkedIn posts directly to Buffer with proper formatting, including automatic splitting of the post text and links block into a first comment.

### Setup

1. Ensure you have a Buffer account with LinkedIn integration enabled
2. Get your Buffer API key from the Buffer dashboard
3. Add to your `.env` file:
   ```
   BUFFER_API_KEY=your_actual_key_here
   ```

### How It Works

Posts are automatically parsed and split:

```
[POST BODY]
👉 Follow my blog for more https://lovednacodeblog.com/

[LINKS BLOCK → becomes first comment in Buffer]
📚 Bioinformatics paper: https://doi.org/10.1093/bioinformatics/btag023
💻 Code: https://github.com/HorvathLab/scSNViz
🔗 Website: https://example.com
```

**What happens when you upload:**
1. **Channel Discovery** — Automatically finds your first LinkedIn channel in Buffer
2. **Post Parsing** — Splits post at the blog URL marker
3. **Scheduling** — Assigns each post the next available time slot from your schedule
4. **API Upload** — Creates the post in Buffer with:
   - **Main text**: Everything up to and including the blog URL line
   - **First comment**: The links block (paper, code, website)
   - **Link attachment**: The paper URL (creates a preview in LinkedIn)
   - **Scheduled time**: From your posting schedule

### Usage Examples

**Upload existing posts to Buffer:**

```bash
uv run python src/post_creator.py buffer \
  --input input/my_posts \
  --start-date 2026-05-14
```

**Full workflow from PDFs to Buffer:**

```bash
uv run python src/post_creator.py all \
  --input input/ \
  --start-date 2026-05-14 \
  --buffer
```

**Output:**
```
Discovering LinkedIn channel in Buffer...
Using channel ID: 651e550d8af0c048f67ec48c
Found 3 LinkedIn post(s).

✓ paper1.txt → scheduled for 2026-05-14 09:00 (ID: post_123)
✓ paper2.txt → scheduled for 2026-05-15 10:30 (ID: post_124)
✓ paper3.txt → scheduled for 2026-05-16 09:00 (ID: post_125)

Done uploading to Buffer.
```

### Post Structure Reference

Ensure your `.txt` posts follow this format:

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

**⚠️ Critical:** The `👉 Follow my blog for more https://lovednacodeblog.com/` line **must** be present to split the post correctly.

### Troubleshooting Buffer API

**Error: BUFFER_API_KEY not found**
```
ValueError: BUFFER_API_KEY not found in environment. Please add it to your .env file.
```
Add `BUFFER_API_KEY=your_key` to `.env` and restart.

**Error: No LinkedIn channels found**
```
RuntimeError: No LinkedIn channels found in Buffer account
```
Ensure you have:
- A Buffer account with LinkedIn integration enabled
- At least one LinkedIn profile connected to your Buffer account

**Error: GraphQL validation errors**
```
RuntimeError: Buffer API error: [{'message': 'Field ... '}]
```
This usually means:
- Post body or first comment is malformed
- The scheduled time is in the past (use a future date)
- Your API key has expired or lacks permissions
- The `.txt` file is missing the required blog URL marker

Check that your `.txt` files contain the exact blog URL marker and are structured correctly.

**Error: Post scheduled in the past**
Ensure your `--start-date` is today or in the future. Buffer doesn't accept past dates.

## Output Files

For each processed PDF, the following files are generated in the input folder:

| File | Description |
|------|-------------|
| `{name}.txt` | Final LinkedIn post (includes links block) |
| `{name}.json` | Extracted structured data (title, authors, bullet points, etc.) |
| `{name}.md` | Bullet points with supporting text in Markdown format |
| `{name}_1.png`, `{name}_2.png`, ... | Extracted figures from the PDF |
| `{name}_selected.png` | Best selected image (as chosen by GPT-4o) |
| `{name}.images.json` | Image metadata with imgbb URLs |
| `{name}_checker_report.json` | Validation results from checkers (extraction & LinkedIn quality checks) |
| `000_buffer_upload.csv` | Buffer-ready CSV with posting times (in input folder) |

## Architecture

The application uses a **two-chain LangChain pipeline with validation checkers**:

```
PDF → Extract Chain → [Extraction Checker] ←→ retry → JSON
 ↓                                                      ↓
Extract Images (PyMuPDF) → Upload imgbb → Select Best (GPT-4o) → images.json
                                                        ↓
                      LinkedIn Chain → [LinkedIn Checker] ←→ retry → Final Post
                                                        ↓
                          CSV Generation or Buffer API Upload
```

**Stage 1 - Extraction** (uses `gpt-4.1`):
- Loads PDF via PyPDFLoader
- Loads optional sidecar metadata for alternative sources
- Extracts structured data: authors, title, journal, bullet points, links
- Returns JSON with `response_format: json_object`
- Validated by `ExtractionChecker`

**Image Extraction**:
- Extracts images from PDF using PyMuPDF
- Filters small images (<200px) to exclude logos/icons
- Uploads all images to imgbb
- Uses GPT-4o vision to select the most impactful figure
- Saves metadata with imgbb URLs to `.images.json`

**Stage 2 - Post Generation** (uses `gpt-4-mini`):
- Takes extracted JSON as input
- Applies detailed formatting rules (title structure, emoji usage, style guidelines)
- Outputs a polished LinkedIn post with links block
- Validated by `LinkedInChecker`

**Stage 3 - Distribution**:
- **Option A**: Export to `000_buffer_upload.csv` for manual Buffer import (includes separator line)
- **Option B**: Upload directly via Buffer GraphQL API with links as first comment (no separator)

## Project Structure

```
linkedin_posts/
├── src/
│   ├── post_creator.py           # Main application
│   └── checkers/                 # Validation checkers
│       ├── __init__.py
│       ├── base.py               # CheckResult, BaseChecker, generate_with_retry()
│       ├── extraction_checker.py  # Validate extracted JSON
│       └── linkedin_checker.py    # Validate final posts
├── input/                        # Place PDFs here to process
├── templates/
│   ├── Buffer_LinkedIn_Template.csv
│   └── posting_schedule.csv
├── .env                          # Your API keys
├── .claude/                      # Claude Code project files
├── pyproject.toml
├── CLAUDE.md                     # Detailed architecture documentation
└── README.md
```

## Environment

Requires Python 3.11+ and the dependencies listed in `pyproject.toml`:

- Python 3.11+
- uv for package management
- LangChain + LangChain OpenAI for LLM interactions
- pypdf for PDF parsing
- PyMuPDF (fitz) for image extraction
- requests for API calls
- python-dotenv for environment configuration

## Advanced Usage

### Batch Processing with Different Schedules

Process multiple batches with different posting schedules:

```bash
# Batch 1: Posts for May
uv run python src/post_creator.py all \
  --input input/batch_1 \
  --start-date 2026-05-01

# Batch 2: Posts for June with different schedule
uv run python src/post_creator.py all \
  --input input/batch_2 \
  --start-date 2026-06-01 \
  --schedule templates/june_schedule.csv
```

### Dry-run with CSV Export (Before Buffer API)

Generate CSV without uploading to Buffer for manual review:

```bash
uv run python src/post_creator.py csv \
  --input input/ \
  --start-date 2026-05-14
```

Then review `000_buffer_upload.csv` before running the actual Buffer upload.

### Combine CSV and API Exports

Generate both CSV (for backup/reference) and Buffer API upload in one step:

```bash
uv run python src/post_creator.py all \
  --input input/ \
  --start-date 2026-05-14 \
  --buffer
```

This creates:
- `000_buffer_upload.csv` (for reference)
- Scheduled posts in Buffer (via API)

## Troubleshooting

### PDF Processing Issues

**No PDFs found:**
```
Error: No PDF files found in /path/to/folder
```
Ensure PDF files are in the specified folder with `.pdf` extension.

**PDF Parsing Errors:**
If extraction fails repeatedly, check:
- PDF is not corrupted or password-protected
- PDF contains readable text (not scanned image)
- OPENAI_API_KEY is valid and has sufficient quota

### Image Upload Issues

**No images extracted:**
- Some PDFs may have images embedded as objects (not standard images)
- Use `--no-upload` to skip Imgur and inspect locally extracted images

**imgbb upload fails:**
- Verify IMGBB_API_KEY is correct
- Check internet connection
- imgbb API may have rate limits

### Quality Issues

Posts fail validation checks if:
- Extraction is incomplete (missing authors, journal, or bullet points)
- Generated post doesn't meet formatting requirements
- LLM quality score is below threshold (70% for extraction, 75% for LinkedIn)

The system automatically retries up to 3 times with feedback before giving up.

## Support

For detailed architecture and implementation information, see `CLAUDE.md`.

For development and debugging, see the project's `.claude/` folder and plan files.

## License

[Add your license here]
