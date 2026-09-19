# EPC Project Intelligence Platform

A working implementation of `EPC_Project_Intelligence_Platform_Implementation_Plan.md`, built phase by phase. Pure Python standard library (3.10+). You only need `pytest` to run the tests.

```bash
python3 demo.py            # full run on the sample Mumbai DC1 pilot
python3 -m pytest -q tests # 61 tests, one file per phase
```

| Phase | Module | Tests | Plan success gate → how it's tested |
|---|---|---|---|
| 0 Foundation | `epc/store.py`, `epc/rag.py`, `epc/ingest.py` | `test_phase0_foundation.py` | Documents are structured and searchable before any agent logic runs. The audit log is append-only and hash-chained. Each project's data is kept separate from every other project. |
| 1 Verification (Engine 1) | `epc/verification.py`, `epc/llm.py` | `test_phase1_verification.py` | No false negatives on the AmpCore bid's known deviations. Rule checks cover numbers, units, tolerances, standards and redundancy. Checks use the policy version in force on the check date. Fulfilment is scored, and human review is audited. |
| 2 Risk (Engine 2) | `epc/risk.py` | `test_phase2_risk.py` | Backtest: recall of real delays = 1.0 with at least 14 days' warning. Five sub-agents feed risk fusion, and slip propagates along the critical path. Mitigations are ranked, and a vendor switch is only offered for a vendor Engine 1 has cleared. |
| 3 Commissioning (Engine 3) | `epc/commissioning.py` | `test_phase3_commissioning.py` | The UPS system runs end to end: auto/manual split, generated test cases, historian execution with evidence, signed manual results, and NCRs with cited precedents. The package reaches READY only when every blocker is cleared. |
| 4 Integration | `epc/platform.py` | `test_phase4_integration.py` | Event bus between engines. An NCR lowers the vendor's score and flags its open POs. Late equipment puts commissioning cases on hold. A resolved NCR becomes a precedent for the next project. A realised delay updates the vendor's on-time rate. PM, procurement and quality dashboards, plus KPIs. |
| 5 Scale & harden | `epc/platform.py` | `test_phase5_scale.py` | Multi-project portfolio with role/project access control (denials are audited). Precedents are kept separate per client. The auto-clear threshold only loosens when there is evidence to support it. |

## Local stand-ins for AWS services
Each one is marked with a `ponytail:` comment where it's used.

| Plan (AWS) | Here | Swap-in point |
|---|---|---|
| Aurora Postgres + graph layer (edges table) | SQLite, same schema | `Store.__init__` |
| OpenSearch k-NN / pgvector + Bedrock embeddings | TF-IDF cosine | `Index._vec` |
| Textract / Unstructured.io | normalised `.md` / `.txt` clause text | loader in front of `ingest()` |
| EventBridge + Step Functions | in-process `Platform.emit` | `Platform.emit` |
| S3 Object Lock / DynamoDB append log | append-only triggers + SHA-256 hash chain | `Store.audit` |
| BMS/EPMS historian, carrier/port/news feeds | `sample_data/*.json` | `execute_auto(readings)`, `assess(feeds)` |
| Claude on Bedrock | off by default. Set `EPC_LLM=1` (`pip install anthropic`, model `EPC_MODEL`, default `anthropic.claude-opus-5`) | `epc/llm.py` |

## Human-in-the-loop rules the tests enforce
- Only a rule-checked "compliant" result above the confidence threshold can auto-clear. An LLM verdict never auto-clears.
- Overriding a finding requires a written justification.
- Manual commissioning results require an engineer signature. The system rejects a result that contradicts the recorded reading.
- Checks that must stay with an engineer (visual, witness, EPO, isolation, thermography, and similar) are never automated. This list can be set per client.
