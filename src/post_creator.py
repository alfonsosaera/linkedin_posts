#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import re
import csv
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

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
With the full content of the paper do the following tasks.

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
# PROCESS ONE PDF
# ==========================
def process_pdf(pdf_path: str):
    """Process a PDF and generate LinkedIn post with validation."""
    print(f"\n=== Processing PDF: {pdf_path} ===")

    # Initialize checkers
    extraction_checker = ExtractionChecker(max_retries=3, min_quality_score=0.7)
    linkedin_checker = LinkedInChecker(max_retries=3, min_quality_score=0.75)

    # Load PDF
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    paper_text = "\n".join(d.page_content for d in docs)

    # Stage 1: Extract with validation
    print("\n===== EXTRACTION STAGE =====")
    extract_prompt = PromptTemplate.from_template(EXTRACT_PROMPT_TEMPLATE_STR)
    extract_chain = extract_prompt | llm_extract | StrOutputParser()

    parsed, extract_checks = generate_with_retry(
        chain=extract_chain,
        initial_inputs={"paper_text": paper_text},
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
    links_block = parsed.get("links_block", "")

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
# GENERATE BUFFER CSV
# ==========================
def generate_buffer_csv(input_dir: str):
    """Generate Buffer-compatible CSV from LinkedIn post .txt files."""
    input_path = Path(input_dir)

    if not input_path.is_dir():
        print(f"Error: {input_dir} is not a directory.")
        sys.exit(1)

    # Find all .txt files (LinkedIn posts), sorted case-insensitively
    txt_files = sorted(input_path.glob("*.txt"), key=lambda f: f.name.lower())

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
            post_content = txt_file.read_text(encoding="utf-8")
            writer.writerow([post_content, "", "", ""])
            print(f"  Added: {txt_file.name}")

    print(f"\nSaved: {output_path}")


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

    args = parser.parse_args()

    if args.command == "generate":
        folder = args.input

        if not os.path.isdir(folder):
            print(f"Error: {folder} is not a folder.")
            sys.exit(1)

        pdfs = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]

        if not pdfs:
            print("No PDF files found.")
            sys.exit(0)

        print(f"Found {len(pdfs)} PDF(s).")

        for pdf_name in pdfs:
            pdf_path = os.path.join(folder, pdf_name)
            process_pdf(pdf_path)

        print("Done.")

    elif args.command == "csv":
        generate_buffer_csv(args.input)
