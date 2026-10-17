"""Automated test suite verifying the curated evaluation dataset against APICompass.

Runs every evaluation case through execute_case() and asserts:
1. Verdict matches expected verdict ('clean', 'issues_found', 'unable_to_verify').
2. Finding categories match expected violation_type.
3. Verification statuses and abstention reasons match expected values.
4. No unexpected crashes or exceptions.
"""

import pytest

from evaluation.dataset import get_evaluation_dataset, EvaluationCase
from evaluation.runner import execute_case

DATASET_CASES = get_evaluation_dataset()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", DATASET_CASES, ids=lambda c: f"{c.case_id}_{c.category}")
async def test_curated_evaluation_case(case: EvaluationCase) -> None:
    """Execute curated evaluation case and verify correctness of findings and verification status."""
    result = await execute_case(case)
    
    assert result.passed, (
        f"Case {case.case_id} ({case.name}) failed evaluation:\n"
        + "\n".join(f"  - {reason}" for reason in result.failure_reasons)
        + f"\nExpected verdict: {case.expected_verdict}, Actual verdict: {result.actual_verdict}"
        + f"\nExpected category: {case.expected_finding_category}, Actual category: {result.actual_finding_category}"
    )
