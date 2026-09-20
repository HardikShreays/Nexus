# EPC Project Intelligence Platform

A working implementation of `EPC_Project_Intelligence_Platform_Implementation_Plan.md`, built phase by phase. The engines are pure Python standard library (3.10+); the AWS services they bind to are switched on by environment variable, so the same code runs offline on a laptop and deployed on AWS.

```bash
python3 demo.py            # full run on the sample Mumbai DC1 pilot, no AWS account needed
python3 serve.py           # the same run, in a browser at http://localhost:8000
python3 -m pytest -q tests # 67 tests, one file per phase
bash infra/deploy.sh       # deploy to AWS, prints the live Function URL
```

| Phase | Module | Tests | Plan success gate → how it's tested |
|---|---|---|---|
| 0 Foundation | `epc/store.py`, `epc/rag.py`, `epc/ingest.py` | `test_phase0_foundation.py` | Documents are structured and searchable before any agent logic runs. The audit log is append-only and hash-chained. Each project's data is kept separate from every other project. |
| 1 Verification (Engine 1) | `epc/verification.py`, `epc/llm.py` | `test_phase1_verification.py` | No false negatives on the AmpCore bid's known deviations. Rule checks cover numbers, units, tolerances, standards and redundancy. Checks use the policy version in force on the check date. Fulfilment is scored, and human review is audited. |
| 2 Risk (Engine 2) | `epc/risk.py` | `test_phase2_risk.py` | Backtest: recall of real delays = 1.0 with at least 14 days' warning. Five sub-agents feed risk fusion, and slip propagates along the critical path. Mitigations are ranked, and a vendor switch is only offered for a vendor Engine 1 has cleared. |
| 3 Commissioning (Engine 3) | `epc/commissioning.py` | `test_phase3_commissioning.py` | The UPS system runs end to end: auto/manual split, generated test cases, historian execution with evidence, signed manual results, and NCRs with cited precedents. The package reaches READY only when every blocker is cleared. |
| 4 Integration | `epc/platform.py` | `test_phase4_integration.py` | Event bus between engines. An NCR lowers the vendor's score and flags its open POs. Late equipment puts commissioning cases on hold. A resolved NCR becomes a precedent for the next project. A realised delay updates the vendor's on-time rate. PM, procurement and quality dashboards, plus KPIs. |
| 5 Scale & harden | `epc/platform.py` | `test_phase5_scale.py` | Multi-project portfolio with role/project access control (denials are audited). Precedents are kept separate per client. The auto-clear threshold only loosens when there is evidence to support it. |
| 6 AWS | `epc/aws.py`, `epc/llm.py`, `serve.py`, `infra/deploy.sh` | `test_phase6_aws.py` | Every binding is inert without its environment variable, so the other suites stay offline. Documents load from S3 and scans go through Textract. Audit rows mirror to DynamoDB under an append-only condition. Engine events publish to EventBridge. The Lambda handler serves both the page and the state. |

## AWS architecture

```
        Lambda Function URL  ──►  Lambda (python3.12, serve.handler)
                                    │  the three engines, one process
        ┌───────────────┬───────────┼────────────────┬─────────────────┐
        ▼               ▼           ▼                ▼                 ▼
   S3 (versioned)   Textract    Bedrock         DynamoDB          EventBridge
   tender, bids,    scanned     Claude Opus 5   audit rows,       bid.verified,
   policies, IST    pages →     clause          append-only by    risk.assessed,
   procedures       clauses     reasoning       condition         ncr.opened, …
```

| Layer | AWS service | Where it binds | Switched on by |
|---|---|---|---|
| Compute + public URL | Lambda + Function URL | `serve.handler` | always, once deployed |
| Object storage | S3 (versioned, `documents/` prefix) | `aws.read_doc` behind `ingest()` | `EPC_S3_BUCKET` |
| OCR | Textract `DetectDocumentText` | `aws.textract_text` | `EPC_S3_BUCKET` + a scanned file |
| Reasoning | Claude Opus 5 on Bedrock (`anthropic.claude-opus-5`) | `epc/llm.py` | `EPC_LLM=1`, model via `EPC_MODEL` |
| Immutable audit | DynamoDB, append-only condition | `Store.audit` | `EPC_AUDIT_TABLE` |
| Event bus | EventBridge | `Platform.emit` | `EPC_EVENT_BUS` |
| Access control | IAM least-privilege role (per-resource ARNs) | `infra/deploy.sh` | always, once deployed |

`infra/deploy.sh` creates all of it and is safe to re-run. Bedrock needs model access granted for Claude in the target region first; without it the deployment still runs, and clause reasoning stays deterministic.

## Still local, and why
Each is marked with a `ponytail:` comment where it's used.

| Plan (AWS) | Here | Swap-in point |
|---|---|---|
| Aurora Postgres + graph layer (edges table) | SQLite, same schema, rebuilt per cold start | `Store.__init__` |
| OpenSearch k-NN / pgvector + Bedrock embeddings | TF-IDF cosine — fine to thousands of clauses per project | `Index._vec` |
| Multi-page tender PDFs (async Textract + SNS) | synchronous `DetectDocumentText`: images and single-page PDFs | `aws.textract_text` |
| Step Functions targets on the bus | handlers stay in-process; events are published either way | `Platform.emit` |
| BMS/EPMS historian, carrier/port/news feeds | `sample_data/*.json` | `execute_auto(readings)`, `assess(feeds)` |

## Human-in-the-loop rules the tests enforce
- Only a rule-checked "compliant" result above the confidence threshold can auto-clear. An LLM verdict never auto-clears.
- Overriding a finding requires a written justification.
- Manual commissioning results require an engineer signature. The system rejects a result that contradicts the recorded reading.
- Checks that must stay with an engineer (visual, witness, EPO, isolation, thermography, and similar) are never automated. This list can be set per client.
