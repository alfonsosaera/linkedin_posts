# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool that generates LinkedIn posts from scientific paper PDFs using a two-stage LLM pipeline.

## Project Structure

```
linkedin_posts/
├── src/
│   └── post_creator.py      # Main application
├── input/                   # Place PDFs here to process
├── output/                  # Generated files (json, txt, md)
├── templates/
│   └── Buffer_LinkedIn_Template.csv
├── .env
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

## Commands

```bash
# Install dependencies
uv sync

# Run the application
uv run python src/post_creator.py --input input/ --output output/
```

## Architecture

The application uses a **two-chain LangChain pipeline**:

```
PDF → Extract Chain → JSON → LinkedIn Chain → Final Post
```

**Stage 1 - Extraction** (`llm_extract` using `gpt-5.1`):
- Loads PDF via `PyPDFLoader`
- Extracts structured data: authors, title, journal, bullet points, links
- Returns JSON with `response_format: json_object`

**Stage 2 - Post Generation** (`llm_linkedin` using `gpt-5-mini`):
- Takes extracted JSON fields as input
- Applies detailed formatting rules (title structure, emoji usage, style guidelines)
- Outputs a polished LinkedIn post

## Data Flow

1. Place PDF files in `input/` directory
2. Run the script with `--input input/ --output output/`
3. For each PDF, generates in `output/`:
   - `{filename}.json` - extracted structured data
   - `{filename}.txt` - final LinkedIn post
   - `{filename}.md` - bullet points paired with supporting text

## Tech Stack

- Python 3.11
- uv for package management
- LangChain + LangChain OpenAI for LLM interactions
- pypdf for PDF parsing
- python-dotenv for environment configuration

## Environment

Requires `.env` file with OpenAI API key.
