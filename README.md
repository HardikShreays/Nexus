<div align="center">
  <h1>⚡ Algo-Nexus</h1>
  <h3>🌟 Next-Gen EPC Project Intelligence Platform</h3>
  

  <p><em>Three AI engines that verify bids, forecast risk, and automate commissioning — so hyperscale data centre projects stay on schedule, on spec, and audit-ready.</em></p>
</div>

<br>

---

## The Problem

India's data centre pipeline is scaling from ~900 MW (2024) to 2,700+ MW by 2027 — over $15B in capital deployment. Yet **67% of APAC data centre EPC projects overrun schedule by >10%** (Turner & Townsend, 2024).

The root cause isn't capital or demand. It's **information fragmentation**:

- **15,000–40,000 equipment line items** and up to 200 concurrent trade contractors per hyperscale project.
- Specs, bids, RFIs, test records, and change orders live in disconnected systems.
- Nobody catches a non-conforming bid clause, a slipping procurement timeline, or a commissioning test failure until it's already expensive.
- Zero error tolerance for Tier III/IV SLA — yet verification is still manual, spreadsheet-driven, and siloed.

---

## The Solution

Nexus is a single intelligence layer with **three tightly-coupled AI engines** on a shared document/data spine:

| Engine | What it does | Key output |
|---|---|---|
| **Engine 1 — Verification** | Checks every vendor bid clause-by-clause against the tender, design standards, and government policy. Numeric requirements (voltage, efficiency, transfer time) are verified algorithmically; complex clauses get LLM reasoning via Claude Opus 5. | Conformance report, deviation flags, vendor risk score, fulfilment ranking |
| **Engine 2 — Risk Assessment** | Five specialised sub-agents monitor procurement lead times, port congestion, monsoon forecasts, workforce availability, and vendor track records. Slip propagates along the critical path. | Risk score per activity, project slip forecast, ranked mitigations with cost/time trade-offs |
| **Engine 3 — Commissioning QA** | Ingests IST procedures (TIA-942, BICSI, Uptime Tier specs), auto-splits checks into machine-verifiable vs. engineer-only, generates test cases, and executes automatable checks via historian telemetry. Failures open NCRs with RAG-sourced precedent resolutions. | As-commissioned quality package, open NCR register |

All three engines communicate via an **event bus**: an NCR in commissioning instantly lowers the vendor's score in verification; a late shipment holds commissioning test cases; a resolved NCR becomes a precedent for the next project.

---

## Tech Stack & Architecture

### Core Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.10+ (standard library only) | Zero external dependencies for the engine code |
| Database | SQLite (local) → Aurora Postgres (production) | Same schema, swap-in point at `Store.__init__` |
| Vector search | TF-IDF cosine similarity | Swap to OpenSearch k-NN / pgvector at `Index._vec` |
| LLM reasoning | Claude Opus 5 on Bedrock | Off by default; deterministic rule checks run without it |
| Frontend | Vanilla HTML/CSS/JS | Single-page dashboard + interactive landing page |
| Server | Python `http.server` (local) / Lambda Function URL (prod) | No framework overhead |
| Tests | pytest — 67 tests across 7 test files | One file per implementation phase |

### System Architecture (The Three Engines)

```text
                        ┌─────────────────────────────────────────────┐
                        │   COMPANY (EPC Owner / Contractor)           │
                        └───────────────────┬───────────────────────────┘
                                             │ tender issued
                                             ▼
                        ┌─────────────────────────────────────────────┐
                        │  CLOUD PLATFORM (AWS)                        │
                        │  Textract → S3 → Vector/Graph Index          │
                        │  Lambda + Function URL · Bedrock (Claude)    │
                        │  EventBridge · DynamoDB audit · IAM          │
                        └───────────────────┬───────────────────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────────┐
                    ▼                        ▼                            ▼
         ┌──────────────────┐     ┌──────────────────────┐     ┌───────────────────────┐
         │ Tender Document    │     │ Vendor Bids            │     │ Govt Policy / Codes   │
         │ (specs, BOQ,       │     │ (technical + comm'l)  │     │ (TIA-942, BIS, CEA,   │
         │ design standards,  │     │                        │     │ CERC, state DC policy)│
         │ client requirements)│     └──────────┬────────────┘     └──────────┬────────────┘
         └─────────┬──────────┘                │                              │
                    └────────────┬──────────────┴──────────────┬───────────────┘
                                 ▼                              ▼
                    ┌───────────────────────────────────────────────────────┐
                    │  ENGINE 1 — SPECIFICATION & QUALITY                     │
                    │  COMPLIANCE VERIFICATION ENGINE                         │
                    │  RAG-based clause-to-clause matching + policy compliance│
                    │  + vendor timeline & fulfilment-capacity scoring        │
                    │  Output: Conformance report, flagged deviations,        │
                    │  vendor risk score, audit trail entry                   │
                    └───────────────────────┬───────────────────────────────┘
                                             │ approved/flagged vendors,
                                             │ PO data, lead times
                                             ▼
                    ┌───────────────────────────────────────────────────────┐
                    │  ENGINE 2 — PREDICTIVE SCHEDULE & SUPPLY CHAIN          │
                    │  RISK ENGINE  (multi-agent)                             │
                    │  Inputs: schedule (P6/MSP), procurement status,         │
                    │  shipment tracking, workforce availability,             │
                    │  electricity grid/utility hookup timeline,              │
                    │  global equipment shortage signals, geopolitical &      │
                    │  natural-disaster feeds, commodity/price indices        │
                    │  Output: Critical-path risk score + ranked mitigation   │
                    │  options (not just alerts)                              │
                    └───────────────────────┬───────────────────────────────┘
                                             │ site-ready equipment,
                                             │ updated schedule state
                                             ▼
                    ┌───────────────────────────────────────────────────────┐
                    │  ENGINE 3 — COMMISSIONING QUALITY ASSURANCE COPILOT     │
                    │  Ingests test/inspection documents (TIA-942, BICSI,     │
                    │  Uptime Institute Tier specs, IST procedures)           │
                    │  → splits checks: machine-verifiable vs. engineer-only  │
                    │  → auto-generates test cases for both                   │
                    │  → executes automatable checks, routes rest to          │
                    │    engineers with generated test scripts                │
                    │  → RAG over cross-site historical failure/resolution    │
                    │    corpus → recommends fixes for failures               │
                    │  Output: As-commissioned quality package + open NCRs    │
                    └───────────────────────┬───────────────────────────────┘
                                             │
                                             ▼
                    ┌───────────────────────────────────────────────────────┐
                    │  PROJECT KNOWLEDGE GRAPH + FEEDBACK LOOP                │
                    │  Every finding, resolution, deviation, and delay is     │
                    │  written back — becomes training/RAG data for the      │
                    │  next tender, the next risk model run, the next         │
                    │  commissioning cycle (this project AND future ones)     │
                    └───────────────────────────────────────────────────────┘
```

### AWS Deployment & Runtime Architecture

```text
        Lambda Function URL  ──►  Lambda (python3.12, serve.handler)
                                    │  the three engines, one process
        ┌───────────────┬───────────┼────────────────┬─────────────────┐
        ▼               ▼           ▼                ▼                 ▼
   S3 (versioned)   Textract    Bedrock         DynamoDB          EventBridge
   tender, bids,    scanned     Claude Opus 5   audit rows,       bid.verified,
   policies, IST    pages →     clause          append-only by    risk.assessed,
   procedures       clauses     reasoning       condition         ncr.opened, …
```

| AWS Service | Purpose | Env Variable to Enable |
|---|---|---|
| **S3** (versioned) | Object storage for tenders, bids, policies, IST procedures | `EPC_S3_BUCKET` |
| **Textract** | OCR for scanned documents → structured clause text | `EPC_S3_BUCKET` + scanned file |
| **Bedrock** (Claude Opus 5) | LLM reasoning for ambiguous clause verification | `EPC_LLM=1`, model via `EPC_MODEL` |
| **DynamoDB** | Immutable audit trail with append-only condition expressions | `EPC_AUDIT_TABLE` |
| **EventBridge** | Cross-engine event bus (bid.verified, risk.assessed, ncr.opened) | `EPC_EVENT_BUS` |
| **Lambda + Function URL** | Serverless compute + public HTTPS endpoint | Always on once deployed |
| **IAM** | Least-privilege role scoped to per-resource ARNs | Always on once deployed |

Every AWS binding is **inert without its environment variable**. The same codebase runs fully offline on a laptop and deployed on AWS — no code changes, no feature flags.

---

## Local Setup

### Prerequisites

- Python 3.10+ (tested on 3.12 and 3.14)
- No AWS account needed for local development

### Quick Start

```bash
# Clone the repository
git clone https://github.com/HardikShreays/Nexus.git
cd Nexus

# Run the CLI demo (no server, prints results to stdout)
python3 demo.py

# Run the web UI (landing page + product dashboard)
python3 serve.py
# → Landing page:  http://localhost:8000
# → Dashboard:     http://localhost:8000/app.html

# Run the full test suite (install pytest first if needed)
python3 -m venv .venv && source .venv/bin/activate
pip install pytest
python3 -m pytest -q tests
# → 67 passed
```

### Deploy to AWS

```bash
bash infra/deploy.sh
# Creates S3 bucket, DynamoDB table, EventBridge bus, IAM role, and Lambda.
# Prints the live Function URL. Safe to re-run.
```

> **Note:** Bedrock requires model access to be granted for Claude in the target region first. Without it, the deployment still succeeds — clause reasoning simply stays deterministic (rule-based only).

---

## Human-in-the-Loop Guarantees

These rules are enforced by the test suite and cannot be bypassed:

- **LLM verdicts never auto-clear.** Only a deterministic, rule-checked "compliant" result above the confidence threshold can auto-clear a finding. An LLM verdict is recorded for engineer review but never closes a finding on its own.
- **Overrides require justification.** Overriding any finding requires a written justification that is permanently recorded in the audit trail.
- **Manual commissioning requires signatures.** Manual test results require an engineer's signature. The system rejects a result that contradicts the recorded sensor reading.
- **Engineer-only checks stay with engineers.** Visual inspection, witness tests, EPO tests, isolation verification, and thermography are never automated. This list is configurable per client.

---

## Limitations

### Sample Data

The current pilot runs on **synthetic sample data** for the Mumbai DC1 project (24 MW hyperscale data centre). This includes:

- Simulated tender documents and vendor bid responses
- Synthetic schedule data with artificially injected delays
- Mock telemetry readings for UPS commissioning tests
- Pre-seeded historical failure/resolution precedents

The sample data is designed to exercise every code path and demonstrate all engine capabilities, but it does not represent real-world document complexity (multi-hundred-page PDFs, handwritten annotations, poorly scanned images).

### Local-Only Components

| Production Target | Current Local Stand-In | Why |
|---|---|---|
| Aurora Postgres + graph layer | SQLite, rebuilt per cold start | No persistence across Lambda invocations yet |
| OpenSearch k-NN / pgvector | TF-IDF cosine similarity | Fine for thousands of clauses; won't scale to millions |
| Multi-page async Textract + SNS | Synchronous `DetectDocumentText` | Only handles images and single-page PDFs |
| Step Functions on EventBridge | In-process event handlers | Events publish to EventBridge; handlers stay local |
| BMS/EPMS historian feeds | Static JSON files in `sample_data/` | No live telemetry integration yet |

### Other Limitations

- No authentication or user management — the dashboard is open to anyone with the URL.
- No persistent storage on Lambda — state is rebuilt on every cold start.
- Risk model sub-agents use heuristic scoring, not trained ML models.
- No CI/CD pipeline configured yet.

---

## Future Versions

### v2 — Production Hardening
- [ ] Migrate SQLite to Aurora Postgres with persistent graph layer
- [ ] Replace TF-IDF with Bedrock embeddings + OpenSearch k-NN for semantic search
- [ ] Add Cognito-based authentication and role-based access control to the web UI
- [ ] Implement async multi-page Textract pipeline with SNS notifications
- [ ] Add CI/CD with GitHub Actions (lint, test, deploy)

### v3 — Intelligence Expansion
- [ ] Train risk sub-agents on historical project delay data (supervised learning)
- [ ] Live BMS/EPMS historian integration for real-time commissioning execution
- [ ] Multi-project portfolio dashboard with cross-project analytics
- [ ] Automated daily/weekly risk digest emails to PMs
- [ ] Vendor performance benchmarking across projects and clients

### v4 — Scale & Enterprise
- [ ] Multi-tenant architecture with client-siloed data and configurable policies
- [ ] API gateway with rate limiting and webhook integrations (P6, Procore, Aconex)
- [ ] Mobile-responsive commissioning interface for field engineers
- [ ] PDF report generation for audit submissions (Tier III/IV certification packages)
- [ ] SOC 2 / ISO 27001 compliance controls for enterprise deployment

---

## Test Coverage

| Phase | Test File | Tests | What It Validates |
|---|---|---|---|
| 0 Foundation | `test_phase0_foundation.py` | 14 | Document ingestion, taxonomy classification, parameter extraction, graph indexing, tenant isolation, tamper-evident audit |
| 1 Verification | `test_phase1_verification.py` | 18 | Zero false negatives on known deviations, numeric/unit/tolerance/standard checks, policy versioning, fulfilment scoring, LLM never auto-clears |
| 2 Risk | `test_phase2_risk.py` | 9 | Sub-agent signals, critical path propagation, mitigation ranking, vendor-switch constraints, backtest recall = 1.0 |
| 3 Commissioning | `test_phase3_commissioning.py` | 8 | Auto/manual split, test case generation, historian execution, signed results, NCRs with precedents, package readiness |
| 4 Integration | `test_phase4_integration.py` | 7 | Cross-engine event bus, NCR → vendor score, late equipment → hold, resolved NCR → precedent, dashboards & KPIs |
| 5 Scale | `test_phase5_scale.py` | 5 | RBAC enforcement, portfolio rollup, project isolation, client-siloed precedents, evidence-based threshold loosening |
| 6 AWS | `test_phase6_aws.py` | 6 | S3 document loading, Textract OCR, DynamoDB append-only audit, EventBridge publishing, Lambda handler routing |

---

*Built for the India Data Centre EPC Intelligence Challenge.*
