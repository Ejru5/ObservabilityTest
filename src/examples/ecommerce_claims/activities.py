"""
E-commerce claims workflow (wf_ecommerce_claims).

ClaimIntakeAgent → VerificationToolAgent → ResolutionAgent:
classify the claim, verify the order and stock, then decide and execute the resolution.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import mistralai.workflows as workflows

from examples.common import llm, services

SMALL = "mistral-small-latest"
MEDIUM = "mistral-medium-latest"

INVENTORY_TIMEOUT_S = 8.0

_REFUND_TYPES = {"damaged_item", "missing_parcel", "incomplete_order"}


@workflows.activity()
async def classify_claim_intake(claim_id: str, order_id: str, reason: str) -> Dict[str, str]:
    """Classify the claim type and urgency from the customer's reason."""
    text = reason.lower()
    if "damaged" in text:
        claim_type, urgency = "damaged_item", "high"
    elif "never delivered" in text or "missing parcel" in text:
        claim_type, urgency = "missing_parcel", "high"
    elif "wrong" in text:
        claim_type, urgency = "wrong_item", "medium"
    elif "missing" in text:
        claim_type, urgency = "incomplete_order", "low"
    else:
        claim_type, urgency = "defective_item", "medium"

    result = await llm.complete(
        SMALL,
        [
            {"role": "system", "content": "You classify e-commerce claims. Answer with JSON only."},
            {"role": "user", "content": f"Claim {claim_id} on order {order_id}: {reason}"},
        ],
        offline_output=llm.as_json({"claim_type": claim_type, "urgency": urgency}),
        json_mode=True,
    )
    return json.loads(result.content)


@workflows.activity()
async def verify_order_and_inventory_tools(order_id: str, sku: str, warehouse: str) -> Dict[str, Any]:
    """Check the order record and whether a replacement is in stock."""
    order = services.fetch_order_record(order_id)
    stock = services.check_inventory_status(sku, warehouse, timeout=INVENTORY_TIMEOUT_S)
    return {
        "order_id": order_id,
        "order_status": order["status"],
        "paid": order["paid"],
        "sku": sku,
        "in_stock": stock["in_stock"],
    }


@workflows.activity()
async def decide_claim_resolution(claim_id: str, order_id: str, claim_type: str, amount: str) -> Dict[str, Any]:
    """Decide the resolution and, for refund claims, issue the refund."""
    resolution = "refund" if claim_type in _REFUND_TYPES else "replacement"
    result = await llm.complete(
        MEDIUM,
        [
            {"role": "system", "content": "You decide claim resolutions. Answer with JSON only."},
            {"role": "user", "content": f"Decide the resolution for claim {claim_id} ({claim_type}) worth {amount}."},
        ],
        offline_output=llm.as_json({"resolution": resolution, "refund_amount": f"{amount} EUR"}),
        json_mode=True,
    )
    decision = json.loads(result.content)

    if decision["resolution"] != "refund":
        return {"claim_id": claim_id, "resolution": decision["resolution"], "refund": None}

    refund = services.issue_refund(order_id=order_id, amount=decision["refund_amount"])
    return {"claim_id": claim_id, "resolution": "refund", "refund": refund}


@workflows.workflow.define(
    name="wf_ecommerce_claims",
    workflow_display_name="E-commerce Claims",
    workflow_description="Triage a customer claim, verify the order and inventory, and decide the resolution.",
)
class EcommerceClaimsWorkflow:

    @workflows.workflow.entrypoint
    async def run(self, input_data: dict) -> dict:
        claim_id, order_id = input_data["claim_id"], input_data["order_id"]
        intake = await classify_claim_intake(claim_id, order_id, input_data["reason"])
        order = services.fetch_order_record(order_id)
        verification = await verify_order_and_inventory_tools(order_id, order["sku"], order["warehouse"])
        return await decide_claim_resolution(claim_id, order_id, intake["claim_type"], verification["paid"])
