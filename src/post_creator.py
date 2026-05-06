#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import re
import csv
import base64
import shutil
import argparse
import locale
import logging
import datetime
from pathlib import Path
from dotenv import load_dotenv

import fitz  # PyMuPDF
import requests

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from langchain_community.document_loaders import PyPDFLoader
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from checkers import (
    ExtractionChecker,
    LinkedInChecker,
    generate_with_retry,
    CheckResult,
)

load_dotenv()
locale.setlocale(locale.LC_ALL, '')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# ==========================
# MODELS
# ==========================
llm_extract = ChatOpenAI(
    model="gpt-5.1",
    model_kwargs={"response_format": {"type": "json_object"}},
)

llm_linkedin = ChatOpenAI(
    model="gpt-5-mini"
)


# ==========================
# PROMPT 1 — EXTRACT INFO FROM PAPER
# ==========================
EXTRACT_PROMPT_TEMPLATE_STR = """
{metadata_overrides}With the full content of the paper do the following tasks.

1.- Extract publication full author list of the scientific publication. 
Example:
From: 
Article
Open access
Published: 27 March 2025
SIMVI disentangles intrinsic and spatial-induced cellular states in spatial omics data
Mingze Dong, David G. Su, Harriet Kluger, Rong Fan & Yuval Kluger 
Nature Communications volume 16, Article number: 2990 (2025)

publication full author list is: Mingze Dong, David G. Su, Harriet Kluger, Rong Fan & Yuval Kluger 

2.- Extract the publication title **and the publication journal**.

3.- Create the next sentence filling the fields with the data from 1 and 2. 
If one or more fields are not clear, just leave the labeled field:
discuss the publication “{{publication title}}” published in {{publication journal}} by {{publication full author list of the scientific publication}}

4.- Provide the main points as a bullet point list.
The number of bullet points must depend on the content (do NOT force 10 items).
Use only information explicitly present in the full paper text (not only abstract).
Avoid inference based on external knowledge.
Number items as 5.001., 5.002., etc. (increment second digits, keep 5 constant).

After the numbered list, output another list containing **the supporting text** for each point.
Use the SAME numbering format: 5.001. "supporting text here", 5.002. "supporting text here", etc.
First the main points, then the supporting texts.

5.- Provide this block if possible; keep text, icons and emojis:
📚 {{publication journal}} paper: {{publication link}}
💻 Code: {{link to github or similar repository}}
🔗 Website: {{associated website if exists}}
Use ONLY URLs explicitly present in the paper.  
Do NOT guess missing links.

6.- Explain clearly what parts of the paper you accessed (full paper, abstract, figures, etc.) 
and whether paywall/subscription was required.

Finally, produce the final JSON with this structure:

{{
  "objective_sentence": "A single sentence suitable as an objective/intro for a LinkedIn post. Use the sentence created in task 3.",
  "bullet_points": "The full numbered main-points list produced in task 4.",
  "supporting_text_list": "The supporting text list corresponding to each bullet point.",
  "links_block": "The block of lines produced in task 5, including emojis and plain URLs.",
  "data_access_explanation": "The explanation from task 6."
}}

Here is the full text of the paper:
--------------------
{paper_text}
"""


# ==========================
# PROMPT 2 — LINKEDIN POST GENERATOR (FINAL VERSION)
# ==========================
LINKEDIN_PROMPT_TEMPLATE_STR = """
Hello ChatGPT,
I am Alfonso Saera Vila. Make sure to clarify the author of the tools I post about and the journal where the tool was published. 
If you include links, do not generate hyperlinks; show the full link as plain text.

Inputs:
- Objective sentence: {objective_sentence}
- Bullet points: {bullet_points}
- Links block: {links_block}

Your task is to transform this into a SHORT, HIGH-QUALITY LinkedIn post following these rules:

---------------------------- STRUCTURE RULES ----------------------------

1) TITLE  
- First line only.  
- No “Title:” label.  
- Include emojis.  
- NOT the exact paper title.  
- Prefer formats like: “<emoji> <High-level concept>: <Tool name> <emoji>”.
- Prioritize emojis like: 🔬 🧬 🧫 🚀 🧠 💻 🔍 🤖 🧑‍💻 💻 📊 🧪 🏥

2) INTRODUCTION (ONE SENTENCE ONLY)  
Must follow EXACTLY:  
“The study <title>, published in <journal> by <full author list>, introduces <tool name>, <short high-level description>.”

- No first person.  
- No extra sentences.  
- MUST include tool name.

3) MAIN POINTS (📌 — optional, 2–5 items)  
- Select only the most relevant points from the input.  
- Merge, shorten or omit points as needed.  
- NO low-level details (epochs, loss functions, huge numbers of interactions, etc.).  
- Each item = ONE line starting with “📌 ”.

4) OPTIONAL CONCLUSIONS (1–2 max)  
- Start with “✅ ”.  
- ONE line each.

5) OPTIONAL LIMITATION (0–1)  
- Start with “⚠️ ”.  
- ONE line.

6) POST ENDING (before links)
Include EXACTLY:
📢 Join the Conversation 📢  
Share your ideas, methods, and tools in the comments! 👇 💬

👉 Follow my blog for more https://lovednacodeblog.com/

7) LINKS (after ending)
- Show ONLY non-empty lines of {links_block}.  
- Omit empty Code/Website lines.  

---------------------------- STYLE RULES ----------------------------
- Final post must be very short and concise.  
- No “X excels at Y” → use “X is great at Y”.  
- Avoid “seamless”, “seamlessly”.  
- Replace “just took a huge leap forward!” with “made a remarkable advance” or equivalent.  
- No em dashes (—).  
- No section headers.  
- No commentary or meta explanations.  
- Tone: expert, polished, professional.

---------------------------- OUTPUT ----------------------------
Output ONLY the final LinkedIn post. No labels, no extra comments.
"""


# ==========================
# RETRY PROMPT TEMPLATES
# ==========================
EXTRACTION_RETRY_TEMPLATE = """
Your previous extraction attempt had issues that need to be corrected.

PREVIOUS OUTPUT:
{previous_output}

FEEDBACK TO ADDRESS:
{feedback}

Please regenerate the extraction, fixing all the issues mentioned above.
Make sure to output valid JSON with all required fields.

{original_prompt}
"""

LINKEDIN_RETRY_TEMPLATE = """
Your previous LinkedIn post had issues that need to be corrected.

PREVIOUS POST:
{previous_output}

FEEDBACK TO ADDRESS:
{feedback}

Please regenerate the LinkedIn post, fixing all the issues mentioned above.
Follow all the original formatting and style rules carefully.

{original_prompt}
"""


# ==========================
# PAIR BULLET POINTS WITH SUPPORTING TEXT
# ==========================
def create_paired_markdown(bullet_points: str, supporting_text_list: str) -> str:
    """Parse bullet points and supporting texts, return paired Markdown."""

    # Parse bullet points (format: "5.001. Text here")
    bullet_pattern = re.compile(r"(5\.\d{3})\.\s*(.+?)(?=5\.\d{3}\.|$)", re.DOTALL)
    bullets = bullet_pattern.findall(bullet_points)

    # Parse supporting texts (same numbering format)
    support_pattern = re.compile(r"(5\.\d{3})\.\s*(.+?)(?=5\.\d{3}\.|$)", re.DOTALL)
    supports = support_pattern.findall(supporting_text_list)

    # Create lookup for supporting texts
    support_dict = {num: text.strip() for num, text in supports}

    # Build Markdown
    lines = []
    for num, text in bullets:
        lines.append(f"## {num}. {text.strip()}\n")
        if num in support_dict:
            lines.append(f"{support_dict[num]}\n")
        lines.append("")

    return "\n".join(lines)


# ==========================
# HELPER FUNCTIONS
# ==========================
def log_check_results(stage: str, checks: list[CheckResult]):
    """Log checker results for a pipeline stage."""
    logger = logging.getLogger(f"Checker.{stage}")

    for i, check in enumerate(checks):
        status = "PASSED" if check.passed else "FAILED"
        logger.info(f"Attempt {i + 1}: {status}")

        if check.rule_failures:
            for failure in check.rule_failures:
                logger.warning(f"  Rule: {failure}")

        if check.score is not None:
            logger.info(f"  LLM Score: {check.score:.2f}")

        if check.llm_feedback:
            logger.info(f"  LLM Feedback: {check.llm_feedback[:100]}...")


def generate_checker_report(
    extract_checks: list[CheckResult], linkedin_checks: list[CheckResult]
) -> dict:
    """Generate a structured report of all check results."""
    return {
        "extraction": {
            "total_attempts": len(extract_checks),
            "final_passed": extract_checks[-1].passed if extract_checks else False,
            "final_score": extract_checks[-1].score if extract_checks else None,
            "attempts": [
                {
                    "passed": c.passed,
                    "score": c.score,
                    "rule_failures": c.rule_failures,
                    "llm_feedback": c.llm_feedback,
                }
                for c in extract_checks
            ],
        },
        "linkedin": {
            "total_attempts": len(linkedin_checks),
            "final_passed": linkedin_checks[-1].passed if linkedin_checks else False,
            "final_score": linkedin_checks[-1].score if linkedin_checks else None,
            "attempts": [
                {
                    "passed": c.passed,
                    "score": c.score,
                    "rule_failures": c.rule_failures,
                    "llm_feedback": c.llm_feedback,
                }
                for c in linkedin_checks
            ],
        },
    }


# ==========================
# IMAGE EXTRACTION AND PROCESSING
# ==========================
def extract_images_from_pdf(pdf_path: str, min_size: int = 200) -> list[dict]:
    """Extract all images from PDF using PyMuPDF.

    Args:
        pdf_path: Path to the PDF file
        min_size: Minimum width/height to filter out small images (logos, icons)

    Returns:
        List of dicts with image data, extension, dimensions, and page number
    """
    doc = fitz.open(pdf_path)
    images = []

    for page_num, page in enumerate(doc):
        for img in page.get_images():
            xref = img[0]
            base_image = doc.extract_image(xref)

            # Filter small images (likely icons/logos)
            if base_image["width"] > min_size and base_image["height"] > min_size:
                images.append({
                    "data": base_image["image"],
                    "ext": base_image["ext"],
                    "width": base_image["width"],
                    "height": base_image["height"],
                    "page": page_num,
                })

    doc.close()
    return images


def upload_to_imgbb(image_path: str) -> str | None:
    """Upload image to imgbb, return URL.

    Requires IMGBB_API_KEY in environment variables.
    """
    api_key = os.getenv("IMGBB_API_KEY")
    if not api_key:
        logging.warning("IMGBB_API_KEY not set, skipping upload")
        return None

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    response = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": api_key, "image": image_data},
        timeout=30,
    )

    if response.status_code == 200:
        return response.json()["data"]["url"]
    else:
        logging.warning(f"imgbb upload failed: {response.status_code} - {response.text}")
        return None


def select_best_image(image_paths: list[str], paper_context: str) -> int | None:
    """Use GPT-4o vision to select the most impactful figure.

    Args:
        image_paths: List of paths to candidate images
        paper_context: Context about the paper (title, objective)

    Returns:
        Index of selected image, or None if no good candidates
    """
    if not image_paths:
        return None

    # Build messages with images for GPT-4o
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    llm_vision = ChatOpenAI(model="gpt-4o")

    # Encode images as base64
    image_contents = []
    for i, path in enumerate(image_paths):
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        # Determine media type from extension
        ext = Path(path).suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(ext, "image/png")

        image_contents.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{img_b64}"}
        })

    prompt = f"""You are selecting the best figure from a scientific paper for a LinkedIn post.

Paper context: {paper_context}

I'm showing you {len(image_paths)} images extracted from this paper.
Select the ONE image that would be most impactful and engaging for a LinkedIn post about this research.

Criteria:
- Prefer main result figures, architecture diagrams, or method overviews
- Avoid supplementary figures, author photos, journal logos, or decorative elements
- Choose figures that are visually clear and self-explanatory

Respond with ONLY the number (1-{len(image_paths)}) of the best image.
If none of the images are suitable for a LinkedIn post, respond with "NONE".
"""

    message = HumanMessage(content=[{"type": "text", "text": prompt}] + image_contents)

    try:
        response = llm_vision.invoke([message])
        result = response.content.strip()

        if result.upper() == "NONE":
            return None

        # Parse the number
        selected = int(result) - 1  # Convert to 0-indexed
        if 0 <= selected < len(image_paths):
            return selected
        else:
            return None
    except Exception as e:
        logging.warning(f"Image selection failed: {e}")
        return None


def process_images(pdf_path: str, paper_context: str, upload: bool = True) -> dict | None:
    """Extract images from PDF, optionally upload to Imgur, and select the best one.

    Args:
        pdf_path: Path to the PDF file
        paper_context: Context about the paper for image selection
        upload: If True, upload images to Imgur

    Returns:
        Dict with image metadata, or None if no suitable images
    """
    base, _ = os.path.splitext(pdf_path)

    # Extract images
    print("\n===== IMAGE EXTRACTION =====")
    images = extract_images_from_pdf(pdf_path)

    if not images:
        print("No suitable images found in PDF.")
        return None

    print(f"Found {len(images)} candidate image(s).")

    # Save images locally
    image_paths = []
    for i, img in enumerate(images):
        ext = img["ext"] if img["ext"] != "jpeg" else "jpg"
        img_path = f"{base}_{i + 1}.{ext}"
        with open(img_path, "wb") as f:
            f.write(img["data"])
        image_paths.append(img_path)
        print(f"  Saved: {img_path}")

    # Upload to imgbb (if enabled)
    image_data = []
    if upload:
        print("\nUploading to imgbb...")
        for path in image_paths:
            url = upload_to_imgbb(path)
            image_data.append({
                "filename": os.path.basename(path),
                "url": url,
            })
            if url:
                print(f"  Uploaded: {os.path.basename(path)} -> {url}")
            else:
                print(f"  Failed: {os.path.basename(path)}")
    else:
        print("\nSkipping imgbb upload.")
        for path in image_paths:
            image_data.append({
                "filename": os.path.basename(path),
                "url": None,
            })

    # Select best image using vision model
    print("\nSelecting best image...")
    selected_idx = select_best_image(image_paths, paper_context)

    selected_path = None
    if selected_idx is not None:
        print(f"  Selected: {image_data[selected_idx]['filename']}")

        # Copy selected image to {basename}_selected.{ext}
        selected_src = image_paths[selected_idx]
        ext = Path(selected_src).suffix
        selected_path = f"{base}_selected{ext}"
        shutil.copy2(selected_src, selected_path)
        print(f"  Copied to: {selected_path}")
    else:
        print("  No suitable image selected.")

    # Build result
    result = {
        "selected_index": selected_idx,
        "selected_file": os.path.basename(selected_path) if selected_path else None,
        "images": image_data,
    }

    # Save images.json
    json_path = f"{base}.images.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Saved: {json_path}")

    return result


# ==========================
# PROCESS ONE PDF
# ==========================
def process_pdf(pdf_path: str, upload_images: bool = True):
    """Process a PDF and generate LinkedIn post with validation.

    Args:
        pdf_path: Path to the PDF file
        upload_images: If True, upload extracted images to Imgur
    """
    # Initialize checkers
    extraction_checker = ExtractionChecker(max_retries=3, min_quality_score=0.7)
    linkedin_checker = LinkedInChecker(max_retries=3, min_quality_score=0.75)

    # Load PDF
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    paper_text = "\n".join(d.page_content for d in docs)

    # Load optional sidecar metadata (e.g., correct journal/URL when PDF is from an alternative source)
    base_path = os.path.splitext(pdf_path)[0]
    meta_path = base_path + ".meta.json"
    metadata_overrides = ""
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        override_lines = []
        if meta.get("journal"):
            override_lines.append(f"- Publication journal: {meta['journal']}")
        if meta.get("paper_url"):
            override_lines.append(f"- Paper URL: {meta['paper_url']}")
        if override_lines:
            metadata_overrides = (
                "IMPORTANT: Use the following verified metadata instead of extracting "
                "it from the paper text:\n" + "\n".join(override_lines) + "\n\n"
            )
            print(f"Loaded metadata overrides from {meta_path}: {override_lines}")

    # Stage 1: Extract with validation
    print("\n===== EXTRACTION STAGE =====")
    extract_prompt = PromptTemplate.from_template(EXTRACT_PROMPT_TEMPLATE_STR)
    extract_chain = extract_prompt | llm_extract | StrOutputParser()

    parsed, extract_checks = generate_with_retry(
        chain=extract_chain,
        initial_inputs={"paper_text": paper_text, "metadata_overrides": metadata_overrides},
        checker=extraction_checker,
        retry_prompt_template=EXTRACTION_RETRY_TEMPLATE,
        original_prompt_str=EXTRACT_PROMPT_TEMPLATE_STR,
        parse_output=json.loads,
        max_retries=3,
        llm=llm_extract,
    )

    # Log extraction results
    log_check_results("Extraction", extract_checks)

    objective_sentence = parsed.get("objective_sentence", "")
    bullet_points = parsed.get("bullet_points", "")
    supporting_text_list = parsed.get("supporting_text_list", "")

    # Normalize list values to newline-separated strings (LLM sometimes returns arrays)
    if isinstance(bullet_points, list):
        bullet_points = "\n".join(bullet_points)
    if isinstance(supporting_text_list, list):
        supporting_text_list = "\n".join(supporting_text_list)
    links_block = parsed.get("links_block", "")

    # Process images: extract, upload to Imgur, select best
    process_images(pdf_path, objective_sentence, upload=upload_images)

    # Stage 2: Generate LinkedIn post with validation
    print("\n===== LINKEDIN STAGE =====")
    linkedin_prompt = PromptTemplate.from_template(LINKEDIN_PROMPT_TEMPLATE_STR)
    linkedin_chain = linkedin_prompt | llm_linkedin | StrOutputParser()

    linkedin_post, linkedin_checks = generate_with_retry(
        chain=linkedin_chain,
        initial_inputs={
            "objective_sentence": objective_sentence,
            "bullet_points": bullet_points,
            "links_block": links_block,
        },
        checker=linkedin_checker,
        retry_prompt_template=LINKEDIN_RETRY_TEMPLATE,
        original_prompt_str=LINKEDIN_PROMPT_TEMPLATE_STR,
        parse_output=lambda x: x,  # Already a string
        max_retries=3,
        llm=llm_linkedin,
    )

    # Log LinkedIn results
    log_check_results("LinkedIn", linkedin_checks)

    # Generate paired markdown
    paired_md = create_paired_markdown(bullet_points, supporting_text_list)

    # Save outputs next to the PDF
    base, _ = os.path.splitext(pdf_path)
    txt_path = base + ".txt"
    json_path = base + ".json"
    md_path = base + ".md"
    report_path = base + "_checker_report.json"

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(linkedin_post)
    print(f"Saved: {txt_path}")

    json_str = json.dumps(parsed, indent=2, ensure_ascii=False)
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    print(f"Saved: {json_path}")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(paired_md)
    print(f"Saved: {md_path}")

    # Save checker report
    report = generate_checker_report(extract_checks, linkedin_checks)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Saved: {report_path}")

    return {
        "extraction_checks": extract_checks,
        "linkedin_checks": linkedin_checks,
        "final_post": linkedin_post,
    }


# ==========================
# BUFFER API
# ==========================
BUFFER_API_URL = "https://api.buffer.com"

CREATE_LINKEDIN_POST = """
mutation CreateLinkedInPost(
  $channelId: ChannelId!, $text: String!, $url: String!,
  $firstComment: String!, $dueAt: DateTime
) {
  createPost(input: {
    channelId: $channelId
    text: $text
    dueAt: $dueAt
    schedulingType: automatic
    mode: customScheduled
    metadata: {
      linkedin: {
        firstComment: $firstComment
        linkAttachment: { url: $url }
      }
    }
  }) {
    ... on PostActionSuccess {
      post { id status }
    }
  }
}
"""

QUERY_CHANNELS = """
query GetChannels {
  account {
    channels { id name service }
  }
}
"""


def run_buffer_query(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against the Buffer API."""
    api_key = os.environ.get("BUFFER_API_KEY")
    if not api_key:
        raise ValueError(
            "BUFFER_API_KEY not found in environment. "
            "Please add it to your .env file."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {"query": query, "variables": variables or {}}
    resp = requests.post(BUFFER_API_URL, headers=headers, json=payload)
    resp.raise_for_status()

    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Buffer API error: {data['errors']}")

    return data.get("data", {})


def get_linkedin_channel_id() -> str:
    """Discover the first LinkedIn channel ID from the Buffer account."""
    data = run_buffer_query(QUERY_CHANNELS)
    channels = data.get("account", {}).get("channels", [])

    linkedin_channels = [ch for ch in channels if ch.get("service") == "linkedin"]
    if not linkedin_channels:
        raise RuntimeError("No LinkedIn channels found in Buffer account")

    return linkedin_channels[0]["id"]


def parse_post_for_buffer(text: str) -> tuple[str, str, str]:
    """Split post into body and first comment, extract paper URL.

    Returns: (body, first_comment, paper_url)
    """
    blog_marker = "👉 Follow my blog for more https://lovednacodeblog.com/"

    if blog_marker not in text:
        return text, "", ""

    parts = text.split(blog_marker, 1)
    body = (parts[0] + blog_marker).rstrip()
    first_comment = parts[1].strip()

    paper_url = ""
    if first_comment:
        match = re.search(r"https?://\S+", first_comment)
        if match:
            paper_url = match.group(0)

    return body, first_comment, paper_url


def upload_to_buffer(input_dir: str, start_date: datetime.date, schedule_path: str):
    """Upload LinkedIn posts directly to Buffer via GraphQL API."""
    input_path = Path(input_dir)

    if not input_path.is_dir():
        print(f"Error: {input_dir} is not a directory.")
        sys.exit(1)

    print("Discovering LinkedIn channel in Buffer...")
    channel_id = get_linkedin_channel_id()
    print(f"Using channel ID: {channel_id}")

    schedule = load_posting_schedule(schedule_path)
    slots = iter_posting_datetimes(start_date, schedule)

    txt_files = sorted(input_path.glob("*.txt"), key=lambda f: locale.strxfrm(f.name))

    if not txt_files:
        print("No .txt files found.")
        sys.exit(0)

    print(f"Found {len(txt_files)} LinkedIn post(s).")
    print()

    for txt_file in txt_files:
        post_text = txt_file.read_text(encoding="utf-8")
        body, first_comment, paper_url = parse_post_for_buffer(post_text)

        posting_time_str = next(slots)
        dt = datetime.datetime.fromisoformat(posting_time_str.replace(" ", "T"))
        local_tz = datetime.datetime.now().astimezone().tzinfo
        scheduled_at_iso = dt.replace(tzinfo=local_tz).isoformat()

        image_url = ""
        images_json_path = txt_file.with_suffix(".images.json")
        if images_json_path.exists():
            try:
                with open(images_json_path, "r", encoding="utf-8") as f:
                    img_data = json.load(f)
                selected_idx = img_data.get("selected_index")
                if selected_idx is not None and img_data.get("images"):
                    selected_img = img_data["images"][selected_idx]
                    image_url = selected_img.get("url") or ""
            except (json.JSONDecodeError, IndexError, KeyError) as e:
                logging.warning(f"Error reading {images_json_path}: {e}")

        variables = {
            "channelId": channel_id,
            "text": body,
            "url": paper_url or "",
            "firstComment": first_comment,
            "dueAt": scheduled_at_iso,
        }

        try:
            result = run_buffer_query(CREATE_LINKEDIN_POST, variables)
            post_id = result.get("createPost", {}).get("post", {}).get("id", "?")
            print(
                f"✓ {txt_file.name}"
                f" → scheduled for {posting_time_str}"
                f" (ID: {post_id})"
            )
        except Exception as e:
            print(f"✗ {txt_file.name} → ERROR: {e}")

    print("\nDone uploading to Buffer.")


# ==========================
# SCHEDULING HELPERS
# ==========================
_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def load_posting_schedule(path: str) -> dict[int, str]:
    """Read posting_schedule.csv and return {weekday_index: 'HH:MM'}.

    Weekday indices follow datetime.date.weekday(): Mon=0 … Sun=6.
    Raises ValueError if the file is missing/unreadable or has no valid rows.
    """
    schedule: dict[int, str] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("weekday", "").strip().lower()
                time = row.get("time", "").strip()
                if name in _WEEKDAY_NAMES and time:
                    schedule[_WEEKDAY_NAMES[name]] = time
    except FileNotFoundError:
        raise ValueError(f"Schedule file not found: {path}")

    if not schedule:
        raise ValueError(f"No valid weekday/time rows found in {path}")
    return schedule


def iter_posting_datetimes(
    start_date: datetime.date, schedule: dict[int, str]
):
    """Yield 'YYYY-MM-DD HH:MM' strings starting at start_date.

    Advances one calendar day at a time, skipping days whose weekday is
    not present in the schedule dict.
    """
    current = start_date
    while True:
        time_str = schedule.get(current.weekday())
        if time_str is not None:
            yield f"{current.isoformat()} {time_str}"
        current += datetime.timedelta(days=1)


# ==========================
# GENERATE BUFFER CSV
# ==========================
def generate_buffer_csv(input_dir: str, start_date: datetime.date, schedule_path: str):
    """Generate Buffer-compatible CSV from LinkedIn post .txt files."""
    input_path = Path(input_dir)

    if not input_path.is_dir():
        print(f"Error: {input_dir} is not a directory.")
        sys.exit(1)

    # Load posting schedule
    schedule = load_posting_schedule(schedule_path)
    slots = iter_posting_datetimes(start_date, schedule)

    # Find all .txt files (LinkedIn posts), sorted case-insensitively
    txt_files = sorted(input_path.glob("*.txt"), key=lambda f: locale.strxfrm(f.name))

    if not txt_files:
        print("No .txt files found.")
        sys.exit(0)

    print(f"Found {len(txt_files)} LinkedIn post(s).")

    # Output path with 000 prefix to sort to top
    output_path = input_path / "000_buffer_upload.csv"

    # Write CSV with UTF-8 BOM for emoji support
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Text", "Image URL", "Tags", "Posting Time"])

        for txt_file in txt_files:
            post_content = txt_file.read_text(encoding="utf-8") + '\n--------------------------\n'

            # Look for corresponding .images.json file
            image_url = ""
            images_json_path = txt_file.with_suffix(".images.json")
            if images_json_path.exists():
                try:
                    with open(images_json_path, "r", encoding="utf-8") as img_f:
                        img_data = json.load(img_f)
                    selected_idx = img_data.get("selected_index")
                    if selected_idx is not None and img_data.get("images"):
                        selected_img = img_data["images"][selected_idx]
                        image_url = selected_img.get("url") or ""
                except (json.JSONDecodeError, IndexError, KeyError) as e:
                    logging.warning(f"Error reading {images_json_path}: {e}")

            posting_time = next(slots)
            writer.writerow([post_content, image_url, "", posting_time])
            if image_url:
                print(f"  Added: {txt_file.name} (with image) -> {posting_time}")
            else:
                print(f"  Added: {txt_file.name} -> {posting_time}")

    print(f"\nSaved: {output_path}")


# ==========================
# CLI HELPER
# ==========================
def is_pdf_processed(pdf_path: str) -> bool:
    """Check if a PDF has already been fully processed."""
    base, _ = os.path.splitext(pdf_path)
    required = [base + ext for ext in (".txt", ".json", ".md", "_checker_report.json")]
    return all(os.path.exists(f) for f in required)


def run_generate(folder: str, upload_images: bool = True, force: bool = False):
    """Process all PDFs in a folder.

    Args:
        folder: Path to folder containing PDF files
        upload_images: If True, upload extracted images to Imgur
        force: If True, reprocess PDFs even if output files exist
    """
    if not os.path.isdir(folder):
        print(f"Error: {folder} is not a folder.")
        sys.exit(1)

    all_pdfs = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]

    if not all_pdfs:
        print("No PDF files found.")
        sys.exit(0)

    if force:
        pdfs = all_pdfs
    else:
        pdfs = [f for f in all_pdfs if not is_pdf_processed(os.path.join(folder, f))]
        skipped = len(all_pdfs) - len(pdfs)
        if skipped:
            print(f"Skipping {skipped} already-processed PDF(s). Use --force to reprocess.")

    if not pdfs:
        print("All PDFs already processed.")
        return

    print(f"Found {len(pdfs)} PDF(s) to process.")
    if not upload_images:
        print("imgbb upload disabled (images will be extracted locally).")

    for i, pdf_name in enumerate(pdfs, 1):
        pdf_path = os.path.join(folder, pdf_name)
        print(f"\n=== Processing PDF {i}/{len(pdfs)}: {pdf_name} ===")
        process_pdf(pdf_path, upload_images=upload_images)

    print("Done generating posts.")


# ==========================
# CLI
# ==========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate LinkedIn posts from PDFs and export to Buffer CSV."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Step 1: Generate posts from PDFs
    generate_parser = subparsers.add_parser(
        "generate",
        help="Process PDFs and generate LinkedIn posts"
    )
    generate_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to a folder containing PDF files."
    )
    generate_parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip imgbb upload (images are still extracted locally)."
    )
    generate_parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess all PDFs even if output files already exist."
    )

    # Step 2: Create Buffer CSV from posts
    csv_parser = subparsers.add_parser(
        "csv",
        help="Generate Buffer CSV from existing LinkedIn posts (.txt files)"
    )
    csv_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to a folder containing .txt LinkedIn posts."
    )
    csv_parser.add_argument(
        "--start-date",
        required=True,
        type=datetime.date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="First date to start scheduling posts (e.g. 2026-04-15)."
    )
    csv_parser.add_argument(
        "--schedule",
        default=str(Path(__file__).parent.parent / "templates" / "posting_schedule.csv"),
        metavar="PATH",
        help="Path to posting_schedule.csv (default: templates/posting_schedule.csv)."
    )

    # Step 2b: Upload posts directly to Buffer via API
    buffer_parser = subparsers.add_parser(
        "buffer",
        help="Upload LinkedIn posts directly to Buffer via GraphQL API"
    )
    buffer_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to a folder containing .txt LinkedIn posts."
    )
    buffer_parser.add_argument(
        "--start-date",
        required=True,
        type=datetime.date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="First date to start scheduling posts (e.g. 2026-04-15)."
    )
    buffer_parser.add_argument(
        "--schedule",
        default=str(Path(__file__).parent.parent / "templates" / "posting_schedule.csv"),
        metavar="PATH",
        help="Path to posting_schedule.csv (default: templates/posting_schedule.csv)."
    )

    # Full workflow: generate + csv (+ buffer optional)
    all_parser = subparsers.add_parser(
        "all",
        help="Run full workflow: generate posts from PDFs, then create Buffer CSV"
    )
    all_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to a folder containing PDF files."
    )
    all_parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip imgbb upload (images are still extracted locally)."
    )
    all_parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess all PDFs even if output files already exist."
    )
    all_parser.add_argument(
        "--start-date",
        required=True,
        type=datetime.date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="First date to start scheduling posts (e.g. 2026-04-15)."
    )
    all_parser.add_argument(
        "--schedule",
        default=str(Path(__file__).parent.parent / "templates" / "posting_schedule.csv"),
        metavar="PATH",
        help="Path to posting_schedule.csv (default: templates/posting_schedule.csv)."
    )
    all_parser.add_argument(
        "--buffer",
        action="store_true",
        help="After CSV generation, upload posts directly to Buffer via API."
    )

    args = parser.parse_args()

    if args.command == "generate":
        run_generate(args.input, upload_images=not args.no_upload, force=args.force)

    elif args.command == "csv":
        generate_buffer_csv(args.input, args.start_date, args.schedule)

    elif args.command == "buffer":
        upload_to_buffer(args.input, args.start_date, args.schedule)

    elif args.command == "all":
        run_generate(args.input, upload_images=not args.no_upload, force=args.force)
        print("\n" + "=" * 50)
        print("Creating Buffer CSV...")
        print("=" * 50)
        generate_buffer_csv(args.input, args.start_date, args.schedule)

        if args.buffer:
            print("\n" + "=" * 50)
            print("Uploading to Buffer...")
            print("=" * 50)
            upload_to_buffer(args.input, args.start_date, args.schedule)
