"""
Local stand-ins for the external services the example workflows call (order system,
inventory, payments, document OCR, sanctions screening, credit bureau, layout OCR).

They are deterministic and need no network, and they reproduce the behaviour seen in
production traces: the FRA/AMS/MAD warehouses answer slowly, the bureau rate-limits the
first request for an application, scanned PDFs carry a JBIG2-compressed page 3, and the
sanctions API rejects a missing or expired key.
"""

from __future__ import annotations

import hashlib
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# ── Reference data (mirrors the records behind the production traces) ────────

ORDERS: Dict[str, Dict[str, str]] = {
    "ORD-771204": {"sku": "SKU-4471", "paid": "129.90", "warehouse": "FRA-2"},
    "ORD-771390": {"sku": "SKU-2093", "paid": "59.00", "warehouse": "AMS-1"},
    "ORD-771562": {"sku": "SKU-8810", "paid": "245.50", "warehouse": "FRA-2"},
    "ORD-771718": {"sku": "SKU-3356", "paid": "89.99", "warehouse": "MAD-3"},
    "ORD-771845": {"sku": "SKU-6120", "paid": "19.50", "warehouse": "AMS-1"},
}

APPLICANTS: Dict[str, Dict[str, str]] = {
    "APP-30417": {"name": "Camille Laurent", "dob": "1989-04-17", "doc_number": "19FR48213", "country": "FR"},
    "APP-30452": {"name": "Jonas Weber", "dob": "1994-11-02", "doc_number": "L01X00T47", "country": "DE"},
    "APP-30488": {"name": "Ananya Rao", "dob": "1991-07-29", "doc_number": "Z4418823", "country": "IN"},
    "APP-30523": {"name": "Lucia Navarro", "dob": "1986-01-13", "doc_number": "48213390K", "country": "ES"},
}

APPLICATIONS: Dict[str, Dict[str, str]] = {
    "LN-66102": {"income": "58000", "score": "742", "utilisation": "23%"},
    "LN-66148": {"income": "41000", "score": "701", "utilisation": "31%"},
    "LN-66191": {"income": "92000", "score": "788", "utilisation": "12%"},
    "LN-66237": {"income": "36500", "score": "665", "utilisation": "44%"},
}

DOCUMENTS: Dict[str, Dict[str, str]] = {
    "DOC-18840": {"pages": "14", "regions": "62", "party": "Harbour Estates Ltd", "date": "2026-09-01", "value": "184000.00"},
    "DOC-18871": {"pages": "9", "regions": "41", "party": "Vertex Components GmbH", "date": "2026-08-15", "value": "76500.00"},
    "DOC-18903": {"pages": "22", "regions": "97", "party": "Alder Mutual", "date": "2026-10-01", "value": "12400.00"},
}


def _stable_int(*parts: str, modulo: int = 1000) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16) % modulo


# ── Errors ────────────────────────────────────────────────────────────────────

class ToolTimeoutError(TimeoutError):
    pass


class InvalidToolArgumentsError(ValueError):
    pass


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class OCRProcessingError(Exception):
    pass


# ── Orders, inventory, payments (e-commerce claims) ──────────────────────────

def fetch_order_record(order_id: str) -> Dict[str, str]:
    order = ORDERS.get(order_id, {"sku": "SKU-0000", "paid": "0.00", "warehouse": "FRA-2"})
    return {"order_id": order_id, "status": "delivered", **order}


# p95 response time of each warehouse's stock endpoint, in seconds.
WAREHOUSE_LATENCY_S: Dict[str, float] = {"FRA-2": 9.4, "AMS-1": 8.7, "MAD-3": 9.1}


def check_inventory_status(sku: str, warehouse: str, timeout: float) -> Dict[str, Any]:
    latency = WAREHOUSE_LATENCY_S.get(warehouse, 2.0)
    if latency > timeout:
        raise ToolTimeoutError(
            f"check_inventory_status timed out after {int(timeout * 1000)} ms waiting for warehouse "
            f"{warehouse} (sku={sku})."
        )
    return {"sku": sku, "warehouse": warehouse, "in_stock": 5 + _stable_int(sku, warehouse, modulo=200)}


def issue_refund(order_id: str, amount: Any, currency: str = "EUR") -> Dict[str, str]:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        value = None
    if value is None or not value.is_finite() or value <= 0:
        raise InvalidToolArgumentsError(
            f"issue_refund rejected arguments: 'amount' must be a positive decimal, got '{amount}'."
        )
    return {"refund_id": f"RF-{order_id}", "status": "processed", "amount": f"{value:.2f}", "currency": currency}


# ── Identity documents and sanctions screening (KYC) ─────────────────────────

def extract_document_ocr(applicant_id: str, document_type: str) -> Dict[str, Any]:
    """OCR of the visual zone. Dates are printed DD/MM/YY, as on the issued documents."""
    person = APPLICANTS.get(applicant_id, {"name": "Unknown Applicant", "dob": "1990-01-01",
                                           "doc_number": "X0000000", "country": "FR"})
    year, month, day = person["dob"].split("-")
    text = (
        f"DOCUMENT: {document_type.upper()}\n"
        f"Surname/Given names: {person['name']}\n"
        f"Date of birth: {day}/{month}/{year[2:]}\n"
        f"Document no.: {person['doc_number']}\n"
        f"Nationality: {person['country']}\n"
    )
    return {"document_type": document_type, "mrz_detected": True, "confidence": 0.95, "text": text}


def screen_sanctions(full_name: str, date_of_birth: str) -> Dict[str, Any]:
    key = os.getenv("SANCTIONS_API_KEY", "")
    if not key or key.startswith("expired-"):
        raise AuthenticationError("Sanctions screening API returned HTTP 401 Unauthorized: the API key has expired.")
    return {"matches": 0, "lists_checked": ["OFAC", "EU", "UN"], "full_name": full_name}


# ── Credit bureau (loan underwriting) ────────────────────────────────────────

_BUREAU_RETRY_AFTER_S = 8.0
_bureau_unblocked_at: Dict[str, float] = {}


def pull_credit_bureau_report(application_id: str, bureau: str) -> Dict[str, Any]:
    """The bureau queues a fresh application and answers 429 until Retry-After has passed."""
    now = time.monotonic()
    unblocked_at = _bureau_unblocked_at.setdefault(application_id, now + _BUREAU_RETRY_AFTER_S)
    if now < unblocked_at:
        raise RateLimitError(
            f"{bureau} API returned HTTP 429 Too Many Requests (application {application_id}).",
            retry_after=round(unblocked_at - now, 3),
        )
    record = APPLICATIONS.get(application_id, {"income": "40000", "score": "700", "utilisation": "30%"})
    return {"bureau": bureau, "score": int(record["score"]), "utilisation": record["utilisation"], "open_accounts": 4}


def fetch_full_bureau_report(application_id: str) -> Dict[str, Any]:
    """The complete report: every tradeline with its 48-month payment history (very large)."""
    tradelines: List[Dict[str, Any]] = []
    for i in range(1800):
        tradelines.append({
            "account": f"{application_id}-TL{i:04d}",
            "lender": f"Lender {_stable_int(application_id, str(i), modulo=90):02d}",
            "status": "closed" if i % 3 else "open",
            "history": ["OK"] * 48,
            "note": "Payment received on schedule; no arrears reported for this period.",
        })
    return {"application_id": application_id, "tradelines": tradelines}


# ── Layout OCR (document extraction) ─────────────────────────────────────────

def run_layout_ocr(document_id: str, page: int, dpi: int = 300) -> Dict[str, Any]:
    if page == 3:
        raise OCRProcessingError(
            f"run_layout_ocr failed on {document_id}: page 3 could not be decoded "
            f"(unsupported JBIG2 compression in scanned PDF)."
        )
    doc = DOCUMENTS.get(document_id, {"pages": "1", "regions": "4"})
    per_page = max(1, int(doc["regions"]) // max(1, int(doc["pages"])))
    return {
        "page": page,
        "regions": [{"id": f"p{page}r{r}", "kind": "body" if r else "header"} for r in range(per_page)],
    }


def document_record(document_id: str) -> Optional[Dict[str, str]]:
    return DOCUMENTS.get(document_id)
