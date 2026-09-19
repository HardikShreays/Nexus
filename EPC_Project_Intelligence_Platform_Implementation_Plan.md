# AI-Powered EPC Project Intelligence Platform for Data Centre Construction
## Full Implementation Plan

**Prepared:** 19 September 2026
**Scope:** Response to the India Data Centre EPC Intelligence Challenge — unifying tender/vendor verification, predictive schedule & supply-chain risk, and commissioning quality assurance into one AI-native platform.

---

## 1. Executive Summary

India's data centre pipeline (~900 MW in 2024 → 2,700+ MW by 2027, $15B+ capital deployment) is bottlenecked not by capital or demand but by **information fragmentation**: specs, bids, schedules, procurement status, and test records live in disconnected systems, so nobody catches a non-conformance or a schedule risk until it's already expensive.

We are building a single intelligence layer with **three tightly-coupled AI engines** sitting on a common document/data spine:

1. **Verification Engine** — checks vendor bids/submittals against equipment specs, design standards, client requirements, and government policy before a PO is cut.
2. **Predictive Schedule & Supply Chain Risk Engine** — continuously scores critical-path risk from procurement status, vendor/workforce capacity, shipment tracking, grid connection timelines, geopolitics, natural disasters, and price volatility — and proposes mitigations, not just alerts.
3. **Commissioning Quality Copilot** — ingests test/inspection documents, auto-splits checks into machine-verifiable vs. engineer-required, generates test cases, executes what it can, routes the rest to engineers, and produces a final as-commissioned quality package with RAG-backed failure-resolution recommendations.

All three sit on one **project knowledge graph + document RAG layer**, so a finding in one engine (e.g., a delayed switchgear shipment) automatically surfaces in the others (e.g., commissioning sequence re-planning, compliance re-check on a substitute vendor).

This plan keeps your original tech flow intact and adds the connective tissue needed to make it a platform rather than three separate tools: a shared ingestion/knowledge layer, an orchestration/event bus so engines talk to each other, a human-in-the-loop review layer, and a feedback loop that writes resolved issues back into the RAG corpus.

---

## 2. Problem Recap (Why This, Why Now)

- 15,000–40,000 equipment line items and up to 200 concurrent trade contractors per hyperscale project.
- Thousands of individual test procedures across power, cooling, IT infra — zero error tolerance for Tier III/IV SLA.
- 67% of APAC data centre EPC projects overrun schedule by >10% (Turner & Townsend, 2024), driven mainly by procurement misalignment and commissioning failures.
- Root cause: specs, submittals, RFIs, test records, and change orders sit in disconnected systems — no system builds the intelligence to connect them.

**Design implication:** the platform's core asset isn't any one agent — it's the **unified, continuously-updated project graph** that all three engines read from and write to. Get the ingestion/graph layer wrong and every downstream agent inherits the fragmentation you're trying to remove.

---

## 3. High-Level Architecture (Tech Flow)

Your original flow, retained and extended:

```
                        ┌─────────────────────────────────────────────┐
                        │   COMPANY (EPC Owner / Contractor)           │
                        └───────────────────┬───────────────────────────┘
                                             │ tender issued
                                             ▼
                        ┌─────────────────────────────────────────────┐
                        │  CLOUD PLATFORM (AWS)                        │
                        │  Ingestion → Storage → Vector/Graph Index    │
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

**What I added to your flow (and why):**
- A **shared ingestion/knowledge-graph layer** before the three engines, so all three read/write the same entities (equipment items, vendors, POs, test procedures, NCRs) instead of duplicating parsing logic three times.
- An explicit **feedback loop**: Engine 3's resolved failures and Engine 2's realized risks get written back into the RAG corpus, so the "similar tests failed elsewhere and were solved" recommendation logic in your spec actually has a growing dataset to draw from — not just a static seed corpus.
- A **human-in-the-loop review queue** cutting across all three engines (compliance officer approves/overrides flagged deviations; PM approves mitigation actions; commissioning engineer executes manual test cases) — required for Tier III/IV certification defensibility and for legal liability on anything AI touches.

---

## 4. Engine-by-Engine Design

### 4.1 Engine 1 — Specification & Quality Compliance Verification Engine

**Purpose:** Catch non-conformances between tender specs, client requirements, government/regulatory codes, and what vendors actually bid/submit/ship — before they reach site.

**Inputs:**
- Tender document (equipment specs, BOQ, design standards, client technical requirements)
- Vendor bids (technical datasheets, commercial terms, delivery timelines)
- Government/regulatory policy corpus (CEA grid connectivity norms, BIS standards, state data-centre policies, environmental clearances, fire/electrical codes)
- Historical vendor performance data (if available)

**Processing pipeline:**
1. **Document ingestion & structuring** — OCR/parse tender + bid PDFs/DWGs into structured clauses (Textract/Unstructured.io + layout-aware chunking, since these docs are table- and drawing-heavy).
2. **Clause-level embedding & indexing** — each spec clause, bid clause, and policy clause embedded into a vector store, tagged with equipment category, system (power/cooling/IT), and clause type.
3. **Deviation detection agent** — for each bid clause, retrieves matching spec/policy clauses, runs a structured LLM comparison (spec value, unit, tolerance vs. bid value) → flags exact/partial/no-match with confidence score. Numeric/tabular specs (voltage, capacity, tolerances) get **deterministic rule-based checks**, not just LLM judgment — this is where false negatives are most costly.
4. **Timeline & fulfilment-capacity scoring agent** — cross-references vendor's committed delivery timeline against their historical on-time-delivery rate, current order book (if disclosable), and category-level lead-time benchmarks → produces a fulfilment-confidence score per line item.
5. **Compliance/audit logging** — every flag, override, and approval is written immutably to the audit trail (required for Tier III/IV certification evidence and for any future dispute/claim).

**Output:** Conformance report per vendor/PO, ranked deviation list (severity-tagged), vendor risk & fulfilment score, audit trail entry — feeds Engine 2 (lead time, vendor risk) and the knowledge graph.

**Human-in-the-loop:** Procurement/quality engineer reviews all "flagged" and "no-match" items; only "exact match, high confidence" items can auto-clear. This threshold should start conservative and loosen only after the team trusts the false-positive/negative rate.

---

### 4.2 Engine 2 — Predictive Schedule & Supply Chain Risk Engine

**Purpose:** Surface critical-path risk weeks ahead, with mitigation options, not just red flags.

**Inputs:**
- Project schedule (Primavera P6 / MS Project export or API)
- Procurement status from Engine 1 (PO issued, in-fab, in-transit, at-site) + real logistics/shipment tracking (carrier APIs, port congestion data)
- Workforce availability (trade contractor headcount/skill mix by week)
- Electricity grid/utility connection timeline (a very India-specific critical path item — DISCOM approvals, transformer delivery, substation commissioning)
- External risk signals: global equipment shortage indicators (esp. UPS/switchgear/generators/chillers — semiconductor and copper-dependent categories), geopolitical risk feeds, weather/natural disaster forecasts, commodity/currency price indices (copper, steel, diesel)

**Multi-agent design (orchestrator + specialist sub-agents):**
- **Procurement-risk sub-agent** — equipment-category lead time vs. schedule need-by date, flags at-risk POs.
- **Logistics sub-agent** — geospatial shipment tracking for critical long-lead items (UPS, generators, cooling towers, switchgear); models port/customs/transit delay scenarios.
- **Workforce sub-agent** — trade-by-trade crew availability vs. schedule ramp curve; flags under-resourced work packages.
- **Macro-risk sub-agent** — ingests structured/unstructured external feeds (news, weather, commodity prices) and scores exposure by category and by region.
- **Grid/utility sub-agent** — tracks the DISCOM/substation/transformer approval chain specifically, since power availability is very often the true critical path for Indian DC projects and is poorly tracked in standard EPC schedules.
- **Orchestrator/risk-fusion agent** — combines sub-agent outputs into a single critical-path risk score per activity, and generates **ranked mitigation options** (e.g., "switch to Vendor B — 3 weeks faster, 8% cost premium, spec-compliant per Engine 1" or "expedite via air freight — cost delta ₹X, saves 12 days on critical path").

**Output:** Weekly (or on-demand) critical-path risk dashboard, ranked mitigation recommendations with cost/time tradeoffs, auto-generated risk register entries.

**Why mitigation options and not just alerts:** an alert without an actionable, spec-compliant alternative just adds noise to an already overloaded PM. The mitigation agent should query Engine 1's vendor/spec data live, so any suggested alternative vendor/equipment is pre-validated as spec-compliant.

---

### 4.3 Engine 3 — Commissioning Quality Assurance Copilot

**Purpose:** Guide integrated systems testing, automate what can be automated, route the rest to engineers, and produce certification-ready documentation.

**Processing pipeline:**
1. **Document ingestion** — commissioning standards (TIA-942, BICSI, Uptime Institute Tier specs) + project-specific IST (Integrated Systems Test) procedures + client acceptance criteria.
2. **Check classification agent** — splits every required check into:
   - **Machine-verifiable**: checks against structured data feeds (BMS/EPMS/DCIM readings, sensor logs, meter data, PLC/SCADA outputs) — e.g., "UPS transfer time < 10ms," "chiller redundancy N+1 confirmed via BMS."
   - **Engineer-required**: physical inspection, visual verification, safety walk-downs, anything needing a licensed engineer's sign-off for liability/certification reasons.
3. **Test case generation agent** — for machine-verifiable checks, generates the automated test script/query against the relevant data source; for engineer-required checks, generates a structured test case (procedure, acceptance criteria, expected readings, safety notes) formatted for field execution (mobile/tablet-friendly).
4. **Automated execution** — runs machine-verifiable tests against live BMS/DCIM/SCADA data (or historian data), logs pass/fail with evidence (timestamped readings).
5. **Engineer workflow** — engineer executes assigned manual test cases via a mobile/field app, logs results (photo, reading, signature) — feeds back into the system in real time.
6. **Failure diagnosis & recommendation agent (RAG)** — on any failure/NCR, retrieves similar historical failures from the cross-site corpus (this project's own history + anonymized/aggregated data from other data centres where available) and recommends root cause + resolution, citing the precedent case.
7. **As-commissioned package assembly** — compiles all test records (automated + manual), NCRs, resolutions, and sign-offs into the certification-ready documentation package (Tier III/IV audit trail).

**Output:** Test case library, pass/fail results with evidence, NCR log with RAG-backed resolution recommendations, final as-commissioned quality package.

**Critical design point on the RAG corpus:** cross-data-centre failure/resolution data is commercially sensitive. Practically, this corpus needs to be built primarily from **the project's own history plus your own firm's portfolio** (proprietary moat), with any third-party data limited to anonymized/aggregated public post-mortems (e.g., Uptime Institute abnormal incident reports) — not other clients' raw NCR logs, which they will not license to you. Treat this as a build-over-time asset, not a day-one dataset.

---

## 5. Shared Platform Layer (New — Connective Tissue)

| Layer | Purpose | Suggested Tech |
|---|---|---|
| **Ingestion** | OCR/parse PDFs, DWGs, spreadsheets, emails into structured + embedded data | AWS Textract / Unstructured.io, Apache Tika for office docs |
| **Object storage** | Raw + processed documents | Amazon S3 (versioned, per-project prefix) |
| **Structured data store** | Equipment registry, PO status, vendor master, schedule state | Amazon RDS/Aurora (Postgres) |
| **Vector store** | Clause/spec/test-case embeddings for RAG | Amazon OpenSearch (with k-NN) or pgvector on Aurora |
| **Knowledge graph** | Entity relationships: equipment ↔ vendor ↔ PO ↔ spec clause ↔ test case ↔ NCR | Amazon Neptune, or a lighter graph layer on Postgres (edges table) if team is small |
| **LLM/reasoning layer** | All three engines' agentic reasoning | Claude (via Amazon Bedrock) — Claude Opus/Sonnet for reasoning-heavy compliance/risk-fusion tasks, Claude Haiku for high-volume clause classification |
| **Orchestration** | Multi-agent workflow, event-driven triggers between engines | AWS Step Functions + EventBridge, or LangGraph/an agent framework on top of Bedrock |
| **External data feeds** | Shipment tracking, weather, commodity prices, news/geopolitical signals | Carrier/logistics APIs, weather APIs, commodity price APIs, news APIs — normalized into EventBridge events |
| **Field/mobile app** | Engineer test execution, photo/signature capture | React Native or lightweight PWA |
| **Dashboard/UI** | PM, procurement, quality engineer views | React + a BI layer (or Amazon QuickSight for exec dashboards) |
| **Audit & access control** | Immutable audit trail, role-based access | S3 Object Lock / DynamoDB append log, AWS IAM + Cognito |

---

## 6. Core Data Model (Key Entities)

- **Project** → has many **Packages** (power, cooling, IT, civil)
- **Package** → has many **Equipment Line Items** (linked to spec clauses)
- **Spec Clause** → belongs to a **Standard/Policy Source** (client req, TIA-942, BIS, CEA, etc.)
- **Vendor** → submits **Bids** → each Bid has **Bid Clauses** mapped to Spec Clauses (Engine 1)
- **Purchase Order** → linked to Equipment Line Item, Vendor, Schedule Activity, Shipment
- **Schedule Activity** → linked to POs, Workforce Assignment, Risk Score (Engine 2)
- **Risk Event** → linked to Schedule Activity, source (procurement/logistics/workforce/macro/grid), Mitigation Options
- **Test Procedure** → linked to Commissioning Standard, classified (auto/manual), generates **Test Case**
- **Test Case** → produces **Test Result** → if fail, generates **NCR**
- **NCR** → linked to historical **Precedent Cases** (RAG) → **Resolution**

This graph is what lets a finding in one engine automatically matter to another — e.g., an NCR on a UPS unit (Engine 3) should flag that vendor's fulfilment score (Engine 1) and check if other in-flight POs from that vendor carry similar risk (Engine 2).

---

## 7. Phased Roadmap

### Phase 0 — Discovery & Data Readiness (4–6 weeks)
- Pick one live or recent project as the pilot; inventory what documents/systems actually exist digitally (schedule tool, procurement system, BMS/DCIM access, spec library).
- Define the equipment taxonomy and spec-clause schema jointly with a quality/compliance SME — this schema is the backbone of Engine 1 and won't survive being retrofitted later.
- Stand up the ingestion + storage + vector store layer; do NOT start on agent logic before documents are structured and searchable.

### Phase 1 — MVP: Engine 1 (Verification Engine) (8–10 weeks)
- Why first: highest-precision, most bounded problem (clause matching), earliest trust-builder, and it produces the vendor/PO data Engine 2 needs.
- Deliverable: ingest one tender + a set of vendor bids, produce a deviation report reviewed and validated by a real compliance engineer against their manual process.
- Success gate: false-negative rate on known deviations (test against past project data where the "right answer" is already known) below an agreed threshold before moving on.

### Phase 2 — Predictive Schedule & Risk Engine (10–12 weeks)
- Start with procurement + workforce sub-agents only (data you already have from Engine 1 + schedule tool). Add logistics/macro/grid sub-agents once the core risk-fusion loop is validated — external data integrations (shipment APIs, geopolitical feeds) are the long pole here.
- Success gate: for a past project, backtest whether the engine would have flagged the real delays that occurred, with enough lead time to have mattered.

### Phase 3 — Commissioning Copilot (10–14 weeks, can start in parallel with late Phase 2 if resourcing allows)
- Start with one system (e.g., electrical/UPS) end-to-end: check classification → test case generation → automated execution against BMS data → manual workflow app → NCR + RAG recommendation.
- Success gate: an as-commissioned package for a real test sequence accepted by a commissioning agent/consultant as audit-ready.

### Phase 4 — Integration & Feedback Loop (6–8 weeks)
- Wire the knowledge graph so all three engines read/write shared entities live.
- Build the feedback loop that writes resolved NCRs and realized risks back into each engine's RAG corpus.
- Roll out dashboards for PM, procurement, and quality roles.

### Phase 5 — Scale & Harden (ongoing)
- Multi-project rollout, portfolio-level dashboards, expand RAG corpus across projects (with proper data governance — see Section 8), tune automation thresholds as trust builds.

---

## 8. Security, Compliance & Governance

- **Data sensitivity**: tender pricing, vendor commercial terms, and client requirements are highly confidential — enforce project-level tenant isolation, not just role-based access within a shared pool.
- **Government policy corpus**: keep a versioned, dated snapshot of every regulation/standard used for compliance checks — policies change, and you need to prove which version was in effect when a check ran (audit defensibility).
- **AI-generated content in the audit trail**: every AI-flagged deviation and every auto-executed test result must carry provenance (model version, prompt/inputs, confidence score, human reviewer if applicable). This is non-negotiable for Tier III/IV certification and for any future contractual dispute.
- **Cross-project RAG data (Section 4.3)**: get explicit data-sharing agreements before pooling NCR/failure data across clients' projects, even anonymized. Default to per-client-siloed corpora unless a contract says otherwise.
- **Human sign-off boundary**: define contractually and technically which checks can *never* be fully automated (safety-critical, licensed-engineer-required per code) vs. which can be system-cleared — this boundary should be configurable per client/jurisdiction, not hardcoded.

---

## 9. Success Metrics (KPIs)

| Engine | Leading Indicator | Lagging/Business Indicator |
|---|---|---|
| Verification Engine | % of bid clauses auto-checked vs. manually reviewed; time-to-clear a vendor bid | Reduction in site-discovered non-conformances vs. pre-AI baseline |
| Risk Engine | Lead time between risk flag and actual delay event (target: weeks, not days) | Reduction in schedule overrun % (baseline: 67% of projects >10% overrun) |
| Commissioning Copilot | % of test cases auto-executed vs. manual; time to generate as-commissioned package | Reduction in commissioning cycle duration; NCR recurrence rate |
| Platform-wide | User trust score (engineer override rate on AI recommendations, trending down) | Overall project schedule/cost variance vs. baseline |

---

## 10. Team & Roles (Indicative)

- **Domain SME (EPC/Commissioning)** — non-negotiable from day one; defines the spec-clause schema, the auto/manual test split, and validates every engine's output against real practice.
- **AI/ML Engineers (2–3)** — RAG pipeline, agent orchestration, LLM integration.
- **Data/Platform Engineer (1–2)** — ingestion pipelines, knowledge graph, integrations with schedule/BMS/procurement systems.
- **Frontend Engineer (1–2)** — dashboards + field app.
- **Product/PM** — sequencing, client validation loop.
- **Security/Compliance advisor** (part-time) — audit trail design, data governance, especially for cross-client RAG data.

---

## 11. Key Risks to the Platform Itself

- **Garbage-in documents**: scanned/handwritten/low-quality tender and site documents will break naive OCR — budget real time for document-quality handling, not just the happy path.
- **Integration access**: BMS/DCIM/SCADA and procurement/ERP systems are often locked down or vendor-proprietary — get integration access confirmed with the pilot client *before* committing to the Engine 3 timeline.
- **Over-automation backlash**: if engineers feel the system is overriding their judgment (especially on safety-critical commissioning checks), adoption fails — keep the human-in-the-loop boundary conservative and let trust earn more automation over time, not the reverse.
- **Cold-start RAG corpus**: the "recommend based on similar failures elsewhere" capability is only as good as the corpus — it will be thin at launch; set expectations accordingly and treat corpus-building as a first-class deliverable, not a side effect.

---

## 12. What Was Kept vs. Modified From Your Original Flow

**Kept as-is:** the three-engine structure, the Company→AWS→Tender→Vendor→Verification flow, the risk-factor list (supply delay, grid delay, global shortage, workforce, geopolitical, natural disaster, price fluctuation), the "risk + recommendations" output framing, and the commissioning flow (document → split auto/manual → generate test cases → final recommendation + failures → RAG on historical failures).

**Added:**
- A shared ingestion/knowledge-graph layer beneath all three engines (avoids three separate parsing stacks).
- Explicit inter-engine data flow (Engine 1's vendor/fulfilment scores feed Engine 2; Engine 2's realized delays and Engine 3's NCRs feed back into future Engine 1 vendor risk scoring).
- A feedback loop so the RAG corpora (both risk precedents and commissioning failure precedents) actually grow over time instead of being static.
- A human-in-the-loop review layer with explicit auto-clear thresholds, needed for both trust and Tier III/IV audit defensibility.
- A phased rollout starting with the Verification Engine (bounded, high-trust win) before the harder external-data-dependent Risk Engine and Commissioning Copilot.

---

## 13. Immediate Next Steps

1. Pick the pilot project and confirm what's actually digitized (schedule tool, procurement system, spec library, BMS access) — this determines real Phase 0 scope.
2. Get a domain SME (compliance/quality engineer or commissioning engineer) allocated part-time from day one.
3. Define the equipment/spec-clause taxonomy schema before writing any ingestion code.
4. Confirm data-sharing boundaries for any cross-project RAG corpus before assuming that capability is available.
5. Scope and staff Phase 1 (Verification Engine MVP) as the first buildable, demoable milestone.
