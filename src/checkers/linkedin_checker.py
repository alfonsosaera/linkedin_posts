"""Checker for validating the final LinkedIn post output."""

import json
import re

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from .base import BaseChecker


LINKEDIN_EVALUATION_PROMPT = """
You are evaluating a LinkedIn post about a scientific paper for quality and professionalism.

POST TO EVALUATE:
---
{linkedin_post}
---

EVALUATION CRITERIA (score each 0-10):

1. PROFESSIONAL TONE: Does it sound like an expert sharing valuable information?
   - Not overly promotional
   - Not too casual
   - Appropriate for LinkedIn audience

2. CLARITY: Is the post easy to understand?
   - Clear main message
   - Logical flow
   - No jargon overload

3. ENGAGEMENT: Will readers find this valuable?
   - Interesting hook
   - Actionable or informative content
   - Appropriate call-to-action

4. ACCURACY: Does the post accurately represent the paper?
   - Tool name mentioned
   - Authors/journal credited
   - No exaggerated claims

5. FORMATTING: Is the visual structure clean?
   - Good use of whitespace
   - Emojis used appropriately (not excessive)
   - Easy to scan

Provide your response in this exact JSON format:
{{
    "professional_score": <0-10>,
    "clarity_score": <0-10>,
    "engagement_score": <0-10>,
    "accuracy_score": <0-10>,
    "formatting_score": <0-10>,
    "overall_score": <0.0-1.0>,
    "issues": ["list of specific issues found"],
    "suggestions": ["list of improvement suggestions"]
}}
"""


class LinkedInChecker(BaseChecker):
    """Validates the final LinkedIn post output."""

    FORBIDDEN_PHRASES = [
        "seamless",
        "seamlessly",
        "excels at",
        "took a huge leap forward",
    ]

    REQUIRED_ENDING_PARTS = [
        "Join the Conversation",
        "Follow my blog",
        "lovednacodeblog.com",
    ]

    def __init__(self, *args, **kwargs):
        # LinkedIn posts need slightly higher quality threshold
        kwargs.setdefault("min_quality_score", 0.75)
        super().__init__(*args, **kwargs)

    def run_rule_checks(self, output: str) -> list[str]:
        """Check LinkedIn post against rules."""
        failures = []
        lines = output.strip().split("\n")

        if not lines:
            failures.append("Post is empty")
            return failures

        # 1. Title check (first line)
        first_line = lines[0]
        if first_line.lower().startswith("title:"):
            failures.append("Title line must not start with 'Title:' label")

        # Check for emoji in title
        emoji_pattern = re.compile(
            "["
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F680-\U0001F6FF"  # transport & map
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"
            "\U0001F900-\U0001F9FF"  # supplemental symbols
            "\U00002600-\U000026FF"  # misc symbols
            "]+",
            re.UNICODE,
        )
        if not emoji_pattern.search(first_line):
            failures.append("Title (first line) must contain emojis")

        # 2. Introduction format
        if "The study" not in output:
            failures.append("Introduction must start with 'The study...' format")
        elif "introduces" not in output:
            failures.append("Introduction must mention what the study 'introduces'")

        # 3. Count main points (pin emoji)
        pin_lines = [line for line in lines if line.strip().startswith("\U0001F4CC")]
        if len(pin_lines) > 5:
            failures.append(f"Too many main points ({len(pin_lines)}). Maximum is 5.")

        # 4. Count conclusions (check emoji)
        check_lines = [line for line in lines if line.strip().startswith("\u2705")]
        if len(check_lines) > 2:
            failures.append(f"Too many conclusions ({len(check_lines)}). Maximum is 2.")

        # 5. Count limitations (warning emoji)
        warning_lines = [line for line in lines if line.strip().startswith("\u26A0")]
        if len(warning_lines) > 1:
            failures.append(f"Too many limitations ({len(warning_lines)}). Maximum is 1.")

        # 6. Required ending
        for part in self.REQUIRED_ENDING_PARTS:
            if part.lower() not in output.lower():
                failures.append(f"Missing required ending element: '{part}'")

        # 7. Style violations
        lower_output = output.lower()
        for phrase in self.FORBIDDEN_PHRASES:
            if phrase in lower_output:
                failures.append(f"Contains forbidden phrase: '{phrase}'")

        # 8. Em-dash check
        if "\u2014" in output or "\u2013" in output:
            failures.append("Contains em-dash or en-dash which is not allowed")

        # 9. Length check (rough word count)
        word_count = len(output.split())
        if word_count > 500:
            failures.append(f"Post too long ({word_count} words). Should be concise.")

        return failures

    def run_llm_check(self, output: str) -> tuple[float, str]:
        """Run LLM-based quality evaluation."""
        prompt = PromptTemplate.from_template(LINKEDIN_EVALUATION_PROMPT)
        chain = prompt | self.llm | StrOutputParser()

        response = chain.invoke({"linkedin_post": output})

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
