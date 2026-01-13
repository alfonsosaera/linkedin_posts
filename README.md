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

### Full Workflow (Recommended)

Process PDFs and generate Buffer CSV in one command:

```bash
uv run python src/post_creator.py all --input input/
```

### Skip Imgur Upload

Extract images locally without uploading to Imgur:

```bash
uv run python src/post_creator.py all --input input/ --no-upload
```

### Run Steps Independently

```bash
# Step 1: Generate LinkedIn posts from PDFs
uv run python src/post_creator.py generate --input input/

# Step 2: Create Buffer CSV for bulk upload
uv run python src/post_creator.py csv --input input/
```

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
| `000_buffer_upload.csv` | Buffer-ready CSV (in input folder) |

