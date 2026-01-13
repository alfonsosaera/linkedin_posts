# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool that generates LinkedIn posts from scientific paper PDFs using a two-stage LLM pipeline with validation checkers.

## Project Structure

```
linkedin_posts/
├── src/
│   ├── post_creator.py      # Main application
│   └── checkers/            # Validation checkers
│       ├── __init__.py
│       ├── base.py          # CheckResult, BaseChecker, generate_with_retry()
│       ├── extraction_checker.py
│       └── linkedin_checker.py
├── input/                   # Place PDFs here to process
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

# Full workflow (generate + csv in one command)
uv run python src/post_creator.py all --input input/

# Skip Imgur upload (images still extracted locally)
uv run python src/post_creator.py all --input input/ --no-upload

# Or run steps independently:
# Step 1: Generate LinkedIn posts from PDFs
uv run python src/post_creator.py generate --input input/

# Step 2: Create Buffer CSV for bulk upload
uv run python src/post_creator.py csv --input input/
```

## Architecture

The application uses a **two-chain LangChain pipeline with validation checkers and image extraction**:

```
PDF → Extract Chain → [Extraction Checker] ←→ retry → JSON
 ↓                                                      ↓
Extract Images (PyMuPDF) → Upload Imgur → Select Best (GPT-4o) → images.json
                                                        ↓
                      LinkedIn Chain → [LinkedIn Checker] ←→ retry → Final Post
                                                        ↓
                              CSV Generation → Buffer Upload (with image URL)
```

**Stage 1 - Extraction** (`llm_extract` using `gpt-5.1`):
- Loads PDF via `PyPDFLoader`
- Extracts structured data: authors, title, journal, bullet points, links
- Returns JSON with `response_format: json_object`
- **Validated by `ExtractionChecker`** before proceeding

**Image Extraction** (runs after extraction):
- Extracts images from PDF using PyMuPDF
- Filters small images (<200px) to exclude logos/icons
- Saves images as `{filename}_1.png`, `{filename}_2.png`, etc.
- Uploads all images to Imgur (anonymous, requires `IMGUR_CLIENT_ID`)
- Uses GPT-4o vision to select the most impactful figure
- Saves metadata to `{filename}.images.json`

**Stage 2 - Post Generation** (`llm_linkedin` using `gpt-5-mini`):
- Takes extracted JSON fields as input
- Applies detailed formatting rules (title structure, emoji usage, style guidelines)
- Outputs a polished LinkedIn post
- **Validated by `LinkedInChecker`** before saving

## Checker System

### Core Components (`src/checkers/base.py`)

**`CheckResult`** - Dataclass holding validation results:
- `passed`: bool - whether all checks passed
- `rule_failures`: list[str] - rule-based validation errors
- `llm_feedback`: str | None - quality feedback from LLM evaluation
- `score`: float | None - quality score (0.0-1.0)

**`BaseChecker`** - Abstract base class with:
- `run_rule_checks(output)` - returns list of rule violations
- `run_llm_check(output)` - returns (score, feedback) from LLM evaluation
- `check(output)` - runs both checks and returns `CheckResult`

**`generate_with_retry()`** - Retry loop that:
1. Invokes the chain with inputs
2. Parses output and runs checker
3. If failed, builds retry prompt with feedback and re-invokes
4. Returns (output, check_history) after success or max retries

### Extraction Checker (`src/checkers/extraction_checker.py`)

Validates JSON output from `llm_extract`.

**Rule-based checks:**
- All 5 required fields present: `objective_sentence`, `bullet_points`, `supporting_text_list`, `links_block`, `data_access_explanation`
- `objective_sentence` contains "published in ... by" pattern
- `bullet_points` has at least 3 items with `5.XXX.` numbering format
- `supporting_text_list` count matches bullet points count
- `links_block` contains paper link (not placeholder URLs)

**LLM-based evaluation:**
- Completeness of extraction (main findings captured)
- Accuracy of attribution (authors, journal)
- Bullet point quality (substantive, distinct, logical flow)
- Supporting text relevance

### LinkedIn Checker (`src/checkers/linkedin_checker.py`)

Validates final LinkedIn post from `llm_linkedin`.

**Rule-based checks:**
- Title line has emojis, no "Title:" prefix
- Introduction contains "The study ... introduces" pattern
- Main points count: 2-5 (lines starting with pin emoji)
- Conclusions count: max 2 (lines starting with checkmark emoji)
- Limitations count: max 1 (lines starting with warning emoji)
- Required ending text present ("Join the Conversation", blog link)
- No forbidden phrases: "seamless", "excels at", em-dash
- Word count under 500

**LLM-based evaluation:**
- Professional tone
- Clarity and readability
- Engagement potential
- Formatting quality

### Retry Mechanism

When a check fails, `generate_with_retry()`:
1. Collects feedback from `CheckResult.get_feedback()`
2. Creates new chain with retry prompt template containing:
   - Previous output
   - Feedback (rule violations + LLM suggestions)
   - Original prompt
3. Re-invokes up to `max_retries` times (default: 3)
4. Returns best attempt even if final check fails

### Scoring System

**Two-phase validation flow:**

```
Output → Rule Checks → [if pass] → LLM Evaluation → Final Decision
              ↓                          ↓
         rule_failures              score (0.0-1.0)
```

- **Phase 1**: Rule-based checks run first. If any fail, LLM evaluation is skipped (saves API calls).
- **Phase 2**: LLM evaluation only runs if all rules pass. Returns a score from 0.0 to 1.0.

**Pass/fail logic** (`base.py:74-76`):

```python
passed = len(rule_failures) == 0 and (
    score is None or score >= self.min_quality_score
)
```

A check passes when:
1. Zero rule failures, **AND**
2. Either no LLM score (rules failed, so skipped) **OR** score >= threshold

Note: The `score is None` check is defensive programming. In practice, if rules pass, the LLM check always runs and returns a score. The None check protects against future code changes or edge cases.

**Quality thresholds:**

| Checker | `min_quality_score` |
|---------|---------------------|
| ExtractionChecker | 0.7 (70%) |
| LinkedInChecker | 0.75 (75%) |

**LLM scoring criteria:**

The LLM evaluates sub-criteria (0-10 each) and provides an `overall_score` (0.0-1.0):

*Extraction Checker:*
- `completeness_score` - main findings captured
- `accuracy_score` - faithful attribution
- `bullet_quality_score` - substantive, distinct points
- `support_quality_score` - supporting text relevance

*LinkedIn Checker:*
- `professional_score` - expert tone
- `clarity_score` - readability
- `engagement_score` - value to readers
- `accuracy_score` - faithful representation
- `formatting_score` - visual structure

If `overall_score` falls below the threshold, the check fails and triggers a retry with the `issues` and `suggestions` as feedback.

## Data Flow

**Step 1: Generate posts** (`generate` command)
1. Place PDF files in `input/` directory
2. Run: `uv run python src/post_creator.py generate --input input/`
3. For each PDF:
   - **Extract**: invoke `llm_extract` -> validate with `ExtractionChecker` -> retry if needed
   - **Images**: extract from PDF -> upload to Imgur -> select best with GPT-4o
   - **Generate**: invoke `llm_linkedin` -> validate with `LinkedInChecker` -> retry if needed
4. Generates files next to the original PDF:
   - `{filename}.json` - extracted structured data
   - `{filename}.txt` - final LinkedIn post
   - `{filename}.md` - bullet points paired with supporting text
   - `{filename}_1.png`, `{filename}_2.png`, ... - extracted images
   - `{filename}_selected.png` - copy of the best selected image
   - `{filename}.images.json` - image metadata with Imgur URLs and selected index
   - `{filename}_checker_report.json` - validation results for both stages

**Step 2: Create Buffer CSV** (`csv` command)
1. Run: `uv run python src/post_creator.py csv --input input/`
2. Scans directory for all `.txt` files (LinkedIn posts)
3. Looks for corresponding `.images.json` to get selected image URL
4. Generates `000_buffer_upload.csv` in the input directory (numeric prefix sorts to top)
5. CSV columns: `Text`, `Image URL`, `Tags`, `Posting Time`
6. Posts are ordered alphabetically (case-insensitive), matching folder listing order

## Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `process_pdf()` | `post_creator.py` | Main pipeline orchestrator |
| `generate_with_retry()` | `checkers/base.py` | Retry loop with validation |
| `ExtractionChecker.check()` | `checkers/extraction_checker.py` | Validate extraction JSON |
| `LinkedInChecker.check()` | `checkers/linkedin_checker.py` | Validate LinkedIn post |
| `log_check_results()` | `post_creator.py` | Log checker results to console |
| `generate_checker_report()` | `post_creator.py` | Create JSON report of all attempts |
| `extract_images_from_pdf()` | `post_creator.py` | Extract images using PyMuPDF |
| `upload_to_imgur()` | `post_creator.py` | Upload image to Imgur anonymously |
| `select_best_image()` | `post_creator.py` | Use GPT-4o to select best figure |
| `process_images()` | `post_creator.py` | Orchestrate image extraction pipeline |
| `generate_buffer_csv()` | `post_creator.py` | Create Buffer CSV from .txt posts |
| `run_generate()` | `post_creator.py` | Process all PDFs in a folder |

## Tech Stack

- Python 3.11
- uv for package management
- LangChain + LangChain OpenAI for LLM interactions
- pypdf for PDF parsing
- PyMuPDF (fitz) for image extraction
- requests for Imgur API
- python-dotenv for environment configuration

## Environment

Requires `.env` file with:

```
OPENAI_API_KEY=your_openai_key
IMGUR_CLIENT_ID=your_imgur_client_id
```

Get Imgur Client-ID at: https://api.imgur.com/oauth2/addclient
(Select "Anonymous usage without user authorization")
