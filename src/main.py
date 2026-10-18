"""
Entrypoint — register and run the Loan Processing Workflow worker.

Usage:
    uv run python src/main.py
"""
import asyncio

from dotenv import load_dotenv

load_dotenv(override=True)

import mistralai.workflows as workflows
from workflows.loan_workflow import LoanProcessingWorkflow


async def main() -> None:
    print("Starting Loan Processing Workflow worker...")
    await workflows.run_worker([LoanProcessingWorkflow])


if __name__ == "__main__":
    asyncio.run(main())
