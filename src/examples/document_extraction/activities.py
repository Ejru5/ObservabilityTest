"""
Document extraction workflow (wf_document_extraction).

PageSegmentationAgent → FieldExtractionAgent → ValidationAgent:
segment the scanned document into layout regions, extract its structured fields, validate them.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import mistralai.workflows as workflows

from examples.common import llm, services

SMALL = "mistral-small-latest"
MEDIUM = "mistral-medium-latest"

EXTRACTION_MAX_TOKENS = 512

REQUIRED_FIELDS = ("document_id", "party", "effective_date", "total_value")


@workflows.activity()
async def segment_document_pages(document_id: str, document_type: str, pages: int) -> Dict[str, Any]:
    """Run layout OCR on every page and collect the layout regions."""
    segmented: List[Dict[str, Any]] = []
    for page in range(1, int(pages) + 1):
        layout = services.run_layout_ocr(document_id, page, dpi=300)
        segmented.append(layout)
    return {
        "document_id": document_id,
        "document_type": document_type,
        "pages": segmented,
        "region_count": sum(len(p["regions"]) for p in segmented),
    }


@workflows.activity()
async def extract_structured_fields(handoff_state: Dict[str, Any], document_id: str) -> Dict[str, Any]:
    """Extract party, effective date and total value, citing the regions each came from."""
    pages = handoff_state["segmented_pages"]
    record = services.document_record(document_id) or {"regions": "0", "party": "", "date": "", "value": ""}
    region_ids = [f"r{i:03d}" for i in range(int(record["regions"]))]

    result = await llm.complete(
        MEDIUM,
        [
            {"role": "system", "content": "Extract the key fields and cite every layout region you used. JSON only."},
            {"role": "user", "content": f"Extract the key fields from {handoff_state.get('document_type', 'document')} "
                                        f"{document_id} ({len(pages)} pages)."},
        ],
        offline_output=llm.as_json({
            "document_id": document_id,
            "party": record["party"],
            "effective_date": record["date"],
            "total_value": record["value"],
            "source_regions": [{"region": rid, "used_for": "clause"} for rid in region_ids],
        }),
        max_tokens=EXTRACTION_MAX_TOKENS,
        json_mode=True,
    )
    return json.loads(result.content)


@workflows.activity()
async def validate_extracted_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Check that every required field is present and non-empty."""
    missing = [f for f in REQUIRED_FIELDS if not payload.get(f)]
    return {"document_id": payload.get("document_id"), "valid": not missing, "missing_fields": missing}


@workflows.workflow.define(
    name="wf_document_extraction",
    workflow_display_name="Document Extraction",
    workflow_description="Segment a scanned document, extract its structured fields and validate the payload.",
)
class DocumentExtractionWorkflow:

    @workflows.workflow.entrypoint
    async def run(self, input_data: dict) -> dict:
        document_id = input_data["document_id"]
        handoff = await segment_document_pages(document_id, input_data["document_type"], input_data["pages"])
        payload = await extract_structured_fields(handoff, document_id)
        return await validate_extracted_payload(payload)
