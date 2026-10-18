"""
KYC onboarding workflow (wf_kyc_onboarding).

DocumentIntakeAgent → IdentityExtractionAgent → SanctionsScreeningAgent → OnboardingDecisionAgent:
ingest the identity document, extract the identity fields, screen sanctions lists, decide.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict

from pydantic import BaseModel

import mistralai.workflows as workflows

from examples.common import llm, services

SMALL = "mistral-small-latest"
MEDIUM = "mistral-medium-latest"


class IdentityRecord(BaseModel):
    full_name: str
    date_of_birth: date
    document_number: str
    nationality: str


def _field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}:\s*(.+)", text)
    return match.group(1).strip() if match else ""


@workflows.activity()
async def ingest_identity_documents(applicant_id: str, document_type: str) -> Dict[str, Any]:
    """OCR the uploaded document and check it is legible."""
    ocr = services.extract_document_ocr(applicant_id, document_type)
    return {
        "applicant_id": applicant_id,
        "document_type": document_type,
        "legible": ocr["confidence"] >= 0.8 and ocr["mrz_detected"],
        "confidence": ocr["confidence"],
    }


@workflows.activity()
async def extract_identity_fields(applicant_id: str, document_type: str) -> Dict[str, Any]:
    """Extract full name, date of birth, document number and nationality."""
    text = services.extract_document_ocr(applicant_id, document_type)["text"]
    result = await llm.complete(
        MEDIUM,
        [
            {"role": "system", "content": "Extract identity fields exactly as printed. Answer with JSON only."},
            {"role": "user", "content": f"Extract full name, date of birth, document number and nationality "
                                        f"for applicant {applicant_id}.\n\n{text}"},
        ],
        offline_output=llm.as_json({
            "full_name": _field(text, "Surname/Given names"),
            "date_of_birth": _field(text, "Date of birth"),
            "document_number": _field(text, "Document no."),
            "nationality": _field(text, "Nationality"),
        }),
        json_mode=True,
    )
    record = IdentityRecord.model_validate_json(result.content)
    return record.model_dump(mode="json")


@workflows.activity()
async def screen_sanctions_lists(applicant_id: str, full_name: str, date_of_birth: str) -> Dict[str, Any]:
    """Screen the applicant against the OFAC, EU and UN sanctions lists."""
    result = services.screen_sanctions(full_name=full_name, date_of_birth=date_of_birth)
    return {"applicant_id": applicant_id, "status": "clear" if result["matches"] == 0 else "match", **result}


@workflows.activity()
async def finalize_onboarding_decision(applicant_id: str, screening_status: str) -> Dict[str, str]:
    """Approve, reject or route the applicant to manual review."""
    if screening_status == "clear":
        decision = "approved"
    elif screening_status == "match":
        decision = "rejected"
    else:
        decision = "manual_review"
    return {"applicant_id": applicant_id, "decision": decision}


@workflows.workflow.define(
    name="wf_kyc_onboarding",
    workflow_display_name="KYC Onboarding",
    workflow_description="Ingest identity documents, extract the identity fields, screen sanctions lists and decide onboarding.",
)
class KycOnboardingWorkflow:

    @workflows.workflow.entrypoint
    async def run(self, input_data: dict) -> dict:
        applicant_id, document_type = input_data["applicant_id"], input_data["document_type"]
        await ingest_identity_documents(applicant_id, document_type)
        identity = await extract_identity_fields(applicant_id, document_type)
        screening = await screen_sanctions_lists(applicant_id, identity["full_name"], identity["date_of_birth"])
        return await finalize_onboarding_decision(applicant_id, screening["status"])
