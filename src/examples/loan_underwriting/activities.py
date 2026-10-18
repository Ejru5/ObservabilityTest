"""
Loan underwriting workflow (wf_loan_underwriting).

ApplicationIntakeAgent → CreditAnalysisAgent → RiskScoringAgent → UnderwritingDecisionAgent:
collect the application, analyse the credit history, score the risk, issue the decision.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import mistralai.workflows as workflows

from examples.common import llm, services

SMALL = "mistral-small-latest"
MEDIUM = "mistral-medium-latest"
RISK_MODEL = "mistral-large-latest"

BUREAU_MAX_ATTEMPTS = 3

_RATES = {"A": 4.8, "B": 5.9, "C": 7.9, "D": 10.5}


class RateLimitExhaustedError(Exception):
    pass


@workflows.activity()
async def collect_application_data(application_id: str, amount: float, term_months: int) -> Dict[str, Any]:
    """Load the applicant profile and summarise the application."""
    record = services.APPLICATIONS.get(application_id, {"income": "40000"})
    return {
        "application_id": application_id,
        "amount": float(amount),
        "term_months": int(term_months),
        "income": float(record["income"]),
        "employment": "permanent",
    }


@workflows.activity()
async def analyze_credit_history(application_id: str, bureau: str) -> Dict[str, Any]:
    """Pull the bureau report and summarise the credit history."""
    last_error = None
    for _ in range(BUREAU_MAX_ATTEMPTS):
        try:
            report = services.pull_credit_bureau_report(application_id, bureau)
            break
        except services.RateLimitError as exc:
            last_error = exc
    else:
        raise RateLimitExhaustedError(
            f"pull_credit_bureau_report failed after {BUREAU_MAX_ATTEMPTS} attempts: {last_error}"
        )
    return {"application_id": application_id, **report}


@workflows.activity()
async def compute_risk_score(application_id: str, credit_score: int, income: float, amount: float) -> Dict[str, Any]:
    """Grade the application's risk from the credit analysis."""
    full_report = services.fetch_full_bureau_report(application_id)
    if credit_score >= 780:
        grade = "A"
    elif credit_score >= 700:
        grade = "B"
    elif credit_score >= 650:
        grade = "C"
    else:
        grade = "D"

    result = await llm.complete(
        RISK_MODEL,
        [
            {"role": "system", "content": "You grade loan risk A-D. Answer with JSON only."},
            {"role": "user", "content": (
                f"Compute the risk grade for application {application_id}: credit score {credit_score}, "
                f"income {income} EUR, requested {amount} EUR.\n\n"
                f"Full credit bureau report:\n{json.dumps(full_report)}"
            )},
        ],
        offline_output=llm.as_json({"grade": grade, "dti_within_policy": amount / max(income, 1) < 0.5}),
        json_mode=True,
    )
    return {"application_id": application_id, **json.loads(result.content)}


@workflows.activity()
async def issue_underwriting_decision(application_id: str, grade: str) -> Dict[str, Any]:
    """Approve grades A-C at the grade's rate; decline D."""
    if grade not in _RATES or grade == "D":
        return {"application_id": application_id, "decision": "declined"}
    return {"application_id": application_id, "decision": "approved", "apr": _RATES[grade]}


@workflows.workflow.define(
    name="wf_loan_underwriting",
    workflow_display_name="Loan Underwriting",
    workflow_description="Collect a loan application, analyse the credit history, score the risk and issue a decision.",
)
class LoanUnderwritingWorkflow:

    @workflows.workflow.entrypoint
    async def run(self, input_data: dict) -> dict:
        application_id = input_data["application_id"]
        application = await collect_application_data(application_id, input_data["amount"], input_data["term_months"])
        credit = await analyze_credit_history(application_id, input_data.get("bureau", "Schufa"))
        risk = await compute_risk_score(application_id, credit["score"], application["income"], application["amount"])
        return await issue_underwriting_decision(application_id, risk["grade"])
