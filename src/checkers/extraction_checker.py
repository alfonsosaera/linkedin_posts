"""Checker for validating JSON output from the extraction LLM."""

import json
import re

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from .base import BaseChecker


EXTRACTION_EVALUATION_PROMPT = """
You are evaluating the quality of information extracted from a scientific paper.

EXTRACTED DATA:
{extracted_json}

EVALUATION CRITERIA (score each 0-10):

1. COMPLETENESS: Are all key aspects of the paper captured?
   - Main findings/contributions
   - Methodology overview
   - Key results

2. ACCURACY: Based on the objective_sentence, does the extraction appear faithful?
   - Author attribution looks reasonable
   - Journal mentioned appropriately
   - No obvious fabrications

3. BULLET POINT QUALITY: Are the main points:
   - Substantive (not trivial)
   - Distinct (not repetitive)
   - Well-ordered (logical flow)

4. SUPPORTING TEXT: Does each supporting text actually support its bullet point?

Provide your response in this exact JSON format:
{{
    "completeness_score": <0-10>,
    "accuracy_score": <0-10>,
    "bullet_quality_score": <0-10>,
    "support_quality_score": <0-10>,
    "overall_score": <0.0-1.0>,
    "issues": ["list of specific issues found"],
    "suggestions": ["list of improvement suggestions"]
}}
"""


class ExtractionChecker(BaseChecker):
    """Validates JSON output from the extraction LLM."""

    REQUIRED_FIELDS = [
        "objective_sentence",
        "bullet_points",
        "supporting_text_list",
        "links_block",
        "data_access_explanation",
    ]

    def run_rule_checks(self, output: dict) -> list[str]:
        """Check extraction output against rules."""
        failures = []

        # 1. Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in output or not output[field]:
                failures.append(f"Missing or empty required field: {field}")

        if failures:  # Can't proceed with other checks if fields missing
            return failures

        # 2. Validate objective_sentence format
        obj_sentence = output["objective_sentence"]
        if not re.search(r"published in .+ by", obj_sentence, re.IGNORECASE):
            failures.append(
                "objective_sentence must follow format: 'discuss the publication \"...\" "
                "published in <journal> by <authors>'"
            )

        # 3. Validate bullet_points format
        bullet_points = output["bullet_points"]
        bullet_matches = re.findall(r"5\.\d{3}\.", bullet_points)
        if len(bullet_matches) < 3:
            failures.append(
                f"bullet_points must have at least 3 items with 5.XXX. format. "
                f"Found {len(bullet_matches)}"
            )

        # 4. Validate supporting_text_list matches bullet count
        supporting_text = output["supporting_text_list"]
        support_matches = re.findall(r"5\.\d{3}\.", supporting_text)
        if len(support_matches) != len(bullet_matches):
            failures.append(
                f"supporting_text_list count ({len(support_matches)}) must match "
                f"bullet_points count ({len(bullet_matches)})"
            )

        # 5. Validate links_block has paper link
        links_block = output["links_block"]
        if "paper:" not in links_block.lower() and "http" not in links_block.lower():
            failures.append("links_block must include the paper link")

        # 6. Check URLs are valid (not placeholder text)
        url_pattern = r"https?://[^\s]+"
        urls = re.findall(url_pattern, links_block)
        for url in urls:
            if any(x in url.lower() for x in ["placeholder", "example.com", "xxx"]):
                failures.append(f"Invalid placeholder URL detected: {url}")

        return failures

    def run_llm_check(self, output: dict) -> tuple[float, str]:
        """Run LLM-based quality evaluation."""
        prompt = PromptTemplate.from_template(EXTRACTION_EVALUATION_PROMPT)
        chain = prompt | self.llm | StrOutputParser()

        extracted_json = json.dumps(output, indent=2)
        response = chain.invoke({"extracted_json": extracted_json})

        try:
            result = json.loads(response)
            score = result.get("overall_score", 0.0)
            issues = result.get("issues", [])
            suggestions = result.get("suggestions", [])

            feedback_parts = []
            if issues:
                feedback_parts.append("Issues found:\n" + "\n".join(f"- {i}" for i in issues))
            if suggestions:
                feedback_parts.append("Suggestions:\n" + "\n".join(f"- {s}" for s in suggestions))

            feedback = "\n\n".join(feedback_parts) if feedback_parts else ""
            return score, feedback

        except json.JSONDecodeError:
            self.logger.warning("Failed to parse LLM evaluation response")
            return 0.5, "Could not parse evaluation response"
