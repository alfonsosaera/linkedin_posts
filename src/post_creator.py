#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import re
import argparse
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

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
# PROCESS ONE PDF
# ==========================
def process_pdf(pdf_path: str):
    print(f"\n=== Processing PDF: {pdf_path} ===")

    # Load PDF
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    paper_text = "\n".join(d.page_content for d in docs)

    # Extract JSON
    extract_prompt = PromptTemplate.from_template(EXTRACT_PROMPT_TEMPLATE_STR)
    extract_chain = extract_prompt | llm_extract | StrOutputParser()
    json_str = extract_chain.invoke({"paper_text": paper_text})

    print("\n===== RAW JSON =====\n")

    parsed = json.loads(json_str)
    objective_sentence = parsed.get("objective_sentence", "")
    bullet_points = parsed.get("bullet_points", "")
    supporting_text_list = parsed.get("supporting_text_list", "")
    links_block = parsed.get("links_block", "")

    # LinkedIn post
    linkedin_prompt = PromptTemplate.from_template(LINKEDIN_PROMPT_TEMPLATE_STR)
    linkedin_chain = linkedin_prompt | llm_linkedin | StrOutputParser()

    linkedin_post = linkedin_chain.invoke(
        {
            "objective_sentence": objective_sentence,
            "bullet_points": bullet_points,
            "links_block": links_block,
        }
    )

    print("\n===== LINKEDIN POST =====\n")

    # Generate paired markdown
    paired_md = create_paired_markdown(bullet_points, supporting_text_list)

    # Save outputs next to the PDF
    base, _ = os.path.splitext(pdf_path)
    txt_path = base + ".txt"
    json_path = base + ".json"
    md_path = base + ".md"

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(linkedin_post)
    print(f"Saved: {txt_path}")

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    print(f"Saved: {json_path}")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(paired_md)
    print(f"Saved: {md_path}")


# ==========================
# CLI — SIMPLE FOLDER MODE
# ==========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate LinkedIn posts from PDFs in a folder."
    )

    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to a folder containing PDF files."
    )

    args = parser.parse_args()

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
