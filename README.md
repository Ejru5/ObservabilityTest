# ObservabilityTest

Target repository for Mistral Observability's Auto-Fix Studio. It holds the workflows whose
traces Auto-Fix scans; each traced activity maps to a function of the same name here.

| Workflow | Code |
|---|---|
| `loan-processing-workflow` | `src/workflows/loan_workflow.py` |
| `wf_ecommerce_claims` | `src/examples/ecommerce_claims/activities.py` |
| `wf_kyc_onboarding` | `src/examples/kyc_onboarding/activities.py` |
| `wf_loan_underwriting` | `src/examples/loan_underwriting/activities.py` |
| `wf_document_extraction` | `src/examples/document_extraction/activities.py` |

The example workflows carry the defects seen in their production traces (inventory timeouts,
malformed refund amounts, unparsed document dates, an expired sanctions key, ignored
`Retry-After`, an oversized risk prompt, an undecodable OCR page, a renamed handoff key and
truncated model output), so Auto-Fix has real failures to reproduce and fix.

## Running

```bash
uv sync
uv run python src/main.py
```

The examples call external services through `src/examples/common/services.py` (local,
deterministic stand-ins) and models through `src/examples/common/llm.py`. Set
`EXAMPLES_LLM_MODE=live` and `MISTRAL_API_KEY` to send model calls to the Mistral API; the
default `offline` mode needs no network, which is what Auto-Fix verification sandboxes use.
