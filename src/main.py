"""
Entrypoint — register and run the workflow worker (loan processing plus the examples).

Usage:
    uv run python src/main.py
"""
import asyncio

from dotenv import load_dotenv

load_dotenv(override=True)

import mistralai.workflows as workflows
from workflows.loan_workflow import LoanProcessingWorkflow
from examples.document_extraction.activities import DocumentExtractionWorkflow
from examples.ecommerce_claims.activities import EcommerceClaimsWorkflow
from examples.kyc_onboarding.activities import KycOnboardingWorkflow
from examples.loan_underwriting.activities import LoanUnderwritingWorkflow


async def main() -> None:
    print("Starting workflow worker...")
    await workflows.run_worker([
        LoanProcessingWorkflow,
        EcommerceClaimsWorkflow,
        KycOnboardingWorkflow,
        LoanUnderwritingWorkflow,
        DocumentExtractionWorkflow,
    ])


if __name__ == "__main__":
    asyncio.run(main())
