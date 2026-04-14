# LinkedIn Post Generator

Generate LinkedIn posts from scientific paper PDFs using a two-stage LLM pipeline with automatic image extraction and Buffer integration.

## Features

- **PDF Processing**: Extract structured data from scientific papers (authors, title, journal, key findings)
- **LinkedIn Post Generation**: Create polished, professional posts with proper formatting
- **Image Extraction**: Automatically extract figures from PDFs using PyMuPDF
- **Smart Image Selection**: Use GPT-4o vision to select the most impactful figure
- **Imgur Upload**: Automatically upload images for use in Buffer
- **Buffer CSV Export**: Generate ready-to-upload CSV for Buffer bulk scheduling
- **Validation System**: LLM-based checkers ensure quality output with automatic retry
- **Scheduled Posting**: Assign publication times to each post based on a configurable weekly schedule

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/linkedin_posts.git
cd linkedin_posts

# Install dependencies using uv
uv sync
```

## Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key
IMGUR_CLIENT_ID=your_imgur_client_id  # Optional, for image uploads
```

Get your Imgur Client-ID at: https://api.imgur.com/oauth2/addclient
(Select "Anonymous usage without user authorization")

## Usage

### Full Workflow

Process PDFs and generate Buffer CSV with scheduled posting times:

```bash
uv run python src/post_creator.py all --input input/ --start-date 2026-04-15
```

### Skip Imgur Upload (Recommended)

Extract images locally without uploading to Imgur:

```bash
uv run python src/post_creator.py all --input input/ --no-upload --start-date 2026-04-15
```

### Run Steps Independently

```bash
# Step 1: Generate LinkedIn posts from PDFs
uv run python src/post_creator.py generate --input input/

# Step 2: Create Buffer CSV for bulk upload (with posting schedule)
uv run python src/post_creator.py csv --input input/ --start-date 2026-04-15
```

### Override Journal and Paper URL (Alternative Sources)

When a PDF is downloaded from an alternative source (e.g., bioRxiv) instead of the official journal, create an optional sidecar JSON file to provide the correct journal name and paper URL:

**File: `{filename}.meta.json`** (next to the PDF)

```json
{
  "journal": "Nature Methods",
  "paper_url": "https://doi.org/10.1038/s41592-025-02706-x"
}
```

Both fields are optional. If the sidecar file exists, those values override what the LLM extracts from the PDF text. The sidecar file is entirely optional—if it doesn't exist, the LLM extracts journal and URL directly from the PDF.

Example:
```
input/
  ├── paper.pdf
  ├── paper.meta.json        # Created by you (optional)
  ├── paper.txt              # Generated output
  ├── paper.json             # Generated output
  └── ...
```

## Scheduling Configuration

Posts are assigned publication times based on `templates/posting_schedule.csv`. Edit this file to customize the schedule:

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

- Each post gets the next available weekday slot from the schedule
- Weekdays not defined in the schedule are automatically skipped
- Times are in HH:MM 24-hour format
- Use a custom schedule with `--schedule /path/to/custom_schedule.csv`

## Output Files

For each processed PDF, the following files are generated:

| File | Description |
|------|-------------|
| `{name}.txt` | Final LinkedIn post |
| `{name}.json` | Extracted structured data |
| `{name}.md` | Bullet points with supporting text |
| `{name}_1.png`, `{name}_2.png`, ... | Extracted images |
| `{name}_selected.png` | Best selected image |
| `{name}.images.json` | Image metadata with URLs |
| `{name}_checker_report.json` | Validation results |
| `000_buffer_upload.csv` | Buffer-ready CSV with posting times (in input folder) |

