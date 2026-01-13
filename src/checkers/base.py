"""Base checker infrastructure for LLM output validation."""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@dataclass
class CheckResult:
    """Result of a validation check."""

    passed: bool
    rule_failures: list[str] = field(default_factory=list)
    llm_feedback: str | None = None
    score: float | None = None  # 0.0 to 1.0

    def get_feedback(self) -> str:
        """Combine all feedback for retry prompt."""
        feedback_parts = []
        if self.rule_failures:
            feedback_parts.append(
                "Rule violations:\n" + "\n".join(f"- {f}" for f in self.rule_failures)
            )
        if self.llm_feedback:
            feedback_parts.append(f"Quality feedback:\n{self.llm_feedback}")
        return "\n\n".join(feedback_parts)


class BaseChecker(ABC):
    """Abstract base class for output checkers."""

    def __init__(
        self,
        llm: ChatOpenAI | None = None,
        max_retries: int = 3,
        min_quality_score: float = 0.7,
    ):
        self.llm = llm or ChatOpenAI(model="gpt-5-mini")
        self.max_retries = max_retries
        self.min_quality_score = min_quality_score
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def run_rule_checks(self, output: Any) -> list[str]:
        """Return list of rule violation messages. Empty = all passed."""
        pass

    @abstractmethod
    def run_llm_check(self, output: Any) -> tuple[float, str]:
        """Return (score, feedback) from LLM evaluation."""
        pass

    def check(self, output: Any) -> CheckResult:
        """Run all checks and return combined result."""
        # Rule-based checks
        rule_failures = self.run_rule_checks(output)

        # LLM-based checks (only if rules pass to save API calls)
        score, llm_feedback = None, None
        if not rule_failures:
            score, llm_feedback = self.run_llm_check(output)

        passed = len(rule_failures) == 0 and (
            score is None or score >= self.min_quality_score
        )

        return CheckResult(
            passed=passed,
            rule_failures=rule_failures,
            llm_feedback=llm_feedback if not passed else None,
            score=score,
        )


def generate_with_retry(
    chain,
    initial_inputs: dict,
    checker: BaseChecker,
    retry_prompt_template: str,
    original_prompt_str: str,
    parse_output: Callable[[str], Any] = lambda x: x,
    max_retries: int = 3,
    llm: ChatOpenAI | None = None,
) -> tuple[Any, list[CheckResult]]:
    """
    Generate output with validation and retry on failure.

    Args:
        chain: LangChain chain to invoke
        initial_inputs: Initial inputs for the chain
        checker: Checker instance to validate output
        retry_prompt_template: Template for retry prompt with {previous_output}, {feedback}, {original_prompt}
        original_prompt_str: Original prompt string for reference in retries
        parse_output: Function to parse raw output (e.g., json.loads)
        max_retries: Maximum retry attempts
        llm: LLM to use for retries (extracted from chain if not provided)

    Returns:
        Tuple of (final_output, list_of_check_results)
    """
    logger = logging.getLogger("generate_with_retry")
    check_history = []
    output = None
    raw_output = None
    current_chain = chain
    current_inputs = initial_inputs.copy()

    for attempt in range(max_retries + 1):
        # Generate output
        raw_output = current_chain.invoke(current_inputs)

        try:
            output = parse_output(raw_output)
        except (json.JSONDecodeError, ValueError) as e:
            # If parsing fails, create a failed check result
            result = CheckResult(
                passed=False,
                rule_failures=[f"Failed to parse output: {e}"],
            )
            check_history.append(result)
            logger.warning(f"Attempt {attempt + 1}: Parse error - {e}")

            if attempt < max_retries:
                # Build retry chain with feedback
                retry_prompt = PromptTemplate.from_template(retry_prompt_template)
                retry_llm = llm or checker.llm
                current_chain = retry_prompt | retry_llm | StrOutputParser()
                current_inputs = {
                    "previous_output": raw_output,
                    "feedback": result.get_feedback(),
                    "original_prompt": original_prompt_str.format(**initial_inputs),
                }
            continue

        # Check output
        result = checker.check(output)
        check_history.append(result)

        logger.info(f"Attempt {attempt + 1}: passed={result.passed}, score={result.score}")

        if result.passed:
            return output, check_history

        if attempt < max_retries:
            # Prepare retry with feedback
            feedback = result.get_feedback()
            logger.warning(f"Retry {attempt + 1}/{max_retries}. Feedback: {feedback[:200]}...")

            # Build retry chain with feedback
            retry_prompt = PromptTemplate.from_template(retry_prompt_template)
            retry_llm = llm or checker.llm
            current_chain = retry_prompt | retry_llm | StrOutputParser()
            current_inputs = {
                "previous_output": raw_output,
                "feedback": feedback,
                "original_prompt": original_prompt_str.format(**initial_inputs),
            }

    # Return best attempt even if not perfect
    logger.error("Max retries exceeded. Returning best attempt.")
    return output, check_history
