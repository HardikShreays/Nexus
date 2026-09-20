"""Phase 3 — Engine 3: Commissioning Quality Assurance Copilot.

procedure clauses -> classify (machine-verifiable vs engineer-required) -> generate test cases ->
execute automatable ones against BMS/EPMS historian readings -> engineers record the rest ->
failures open NCRs with RAG-recommended fixes from the client's own precedent corpus ->
as-commissioned package.
"""
from .ingest import UNITS
from .verification import _jaccard, compare

ENGINE = "commissioning/1.0"
# Checks that are never auto-cleared, whatever data exists. Per client/jurisdiction (plan §8) —
# pass your own list to classify(); this is the conservative default.
NEVER_AUTOMATE = ("visual", "inspect", "torque", "witness", "safety", "epo", "emergency", "isolat", "walk",
                  "sign-off", "thermograph", "physical", "smoke", "gas discharge")
SAFETY_NOTES = {
    "power": ["Permit-to-work and LOTO verified", "Arc-flash PPE per incident-energy label", "Two-person rule on live panels"],
    "cooling": ["Permit-to-work verified", "Refrigerant handling per F-gas procedure", "Rotating equipment guarded"],
    "fire": ["Fire panel on test mode, control room informed", "Clear discharge zone"],
}


def bind_point(clause, points):
    """Telemetry point that measures every numeric param of the clause (same equipment, dimension, name)."""
    numeric = [p for p in clause["params"] if p["dim"] != "text"]
    if not numeric:
        return None
    bound = []
    for p in numeric:
        cands = [pt for pt in points if pt["category"] == clause["category"]
                 and UNITS.get(pt["unit"], ("number",))[0] == p["dim"] and _jaccard(p["param"], pt["param"]) > 0]
        if not cands:
            return None
        bound.append(max(cands, key=lambda pt: _jaccard(p["param"], pt["param"])))
    return bound if len({b["id"] for b in bound}) == 1 else None  # one point per auto test keeps evidence simple


def classify(clause, points, never_automate=NEVER_AUTOMATE):
    text = clause["text"].lower()
    blocker = next((k for k in never_automate if k in text), None)
    if blocker:
        return "manual", f"engineer-required keyword '{blocker}'"
    bound = bind_point(clause, points)
    if not bound:
        return "manual", "no telemetry point measures this criterion"
    return "auto", f"measured by {bound[0]['id']}"


def generate_cases(store, project, procedure_doc, points, never_automate=NEVER_AUTOMATE, actor="engine3"):
    cases = []
    for cid in store.neighbors(project, procedure_doc, "contains"):
        c = store.get(project, cid)
        mode, why = classify(c, points, never_automate)
        case = {"procedure": cid, "text": c["text"], "system": c["system"], "category": c["category"],
                "mode": mode, "why": why, "criteria": c["params"], "status": "not_run", "results": []}
        if mode == "auto":
            pt = bind_point(c, points)[0]["id"]
            case.update(point=pt, query=f"SELECT ts, value FROM historian WHERE point = '{pt}' "
                                        f"AND ts BETWEEN :test_start AND :test_end ORDER BY ts")
        else:
            case.update(
                assignee_role="licensed commissioning engineer",
                steps=["Confirm permit-to-work, LOTO and test-window approval",
                       f"Perform: {c['text']}",
                       "Record measured value / observation against each acceptance criterion",
                       "Attach photo evidence", "Sign off with engineer ID"],
                acceptance=[_describe(p) for p in c["params"]] or ["Observation meets procedure text; no defects"],
                safety=SAFETY_NOTES.get(c["system"], ["Site safety induction and permit-to-work"]),
                capture=["reading", "photo", "signature"])
        tid = f"TC:{cid}"
        cases.append(store.put(project, "test_case", tid, case))
        store.link(project, cid, "generates", tid)
    store.audit(project, actor, "commissioning.cases_generated", {
        "engine": ENGINE, "procedure": procedure_doc, "never_automate": list(never_automate),
        "cases": [(c["id"], c["mode"], c["why"]) for c in cases]})
    return cases


def _describe(p):
    if p["dim"] == "text":
        return f"{p['param']} = {p['value']}"
    return f"{p['param']} {p['op']} {p['value']:g} {p['unit']}" + (f" ±{p['tol_pct']:g}%" if p.get("tol_pct") else "")


def _reading_param(crit, value):
    return {**crit, "value": value, "base": value * UNITS.get(crit["unit"], ("", 1))[1], "tol_pct": 0}


def execute_auto(store, index, project, readings, actor="engine3"):
    """readings: {point_id: [[iso_ts, value], ...]} from the historian for the test window."""
    out = []
    for case in store.find(project, "test_case", mode="auto"):
        if case["status"] == "passed":
            continue
        series = readings.get(case["point"], [])
        if not series:
            result = {"status": "no_data", "note": f"no historian data for {case['point']} — rerun or route to engineer"}
        else:
            crit = next(p for p in case["criteria"] if p["dim"] != "text")
            evals = [(ts, val, compare(crit, _reading_param(crit, val), "measured")) for ts, val in series]
            bad = [(ts, val, note) for ts, val, (ok, note) in evals if not ok]
            ts, val, (ok, note) = (bad[0][0], bad[0][1], (False, bad[0][2])) if bad else evals[-1]
            result = {"status": "passed" if not bad else "failed", "samples": len(series),
                      "evidence": {"ts": ts, "value": val, "point": case["point"], "note": note},
                      "violations": len(bad)}
        out.append(_record(store, index, project, case, result, actor))
    return out


def record_manual(store, index, project, case_id, engineer, passed, signature, reading=None, photo=None, notes=""):
    case = store.get(project, case_id)
    if case["mode"] != "manual":
        raise ValueError("automated case — results come from execute_auto")
    if not signature:
        raise ValueError("engineer signature required for every manual result")
    crit = next((p for p in case["criteria"] if p["dim"] != "text"), None)
    if reading is not None and crit:
        ok, note = compare(crit, _reading_param(crit, reading), "measured")
        if ok != passed:
            raise ValueError(f"recorded outcome contradicts reading: {note}")
    result = {"status": "passed" if passed else "failed", "engineer": engineer, "signature": signature,
              "evidence": {"reading": reading, "photo": photo, "notes": notes}}
    return _record(store, index, project, case, result, engineer)


def _record(store, index, project, case, result, actor):
    case = store.update(project, case["id"], status=result["status"], results=case["results"] + [result])
    store.audit(project, actor, "commissioning.result", {"case": case["id"], **result})
    if result["status"] == "failed":
        open_ncr(store, index, project, case, result)
    return case


def _evidence_text(ev):
    """Evidence is a dict (auto: ts/value/point/note, manual: reading/photo/notes) — the readable
    parts, not the dict repr NCR symptoms and the markdown export used to show."""
    ev = ev or {}
    parts = [f"value={ev['value']}" if "value" in ev else None,
             f"reading={ev['reading']}" if "reading" in ev else None,
             ev.get("note") or ev.get("notes")]
    return " · ".join(p for p in parts if p)


# ---------------------------------------------------------------- NCR + RAG
def open_ncr(store, index, project, case, result, actor="engine3"):
    n = len(store.find(project, "ncr")) + 1
    nid = f"NCR-{n:03d}"
    symptom = f"{case['text']} — {_evidence_text(result.get('evidence')) or result.get('note', '')}"
    po = next(iter(store.find(project, "po", category=case["category"])), None)
    ncr = store.put(project, "ncr", nid, {
        "case": case["id"], "category": case["category"], "symptom": symptom, "status": "open",
        "vendor": po and po["vendor"], "po": po and po["id"],
        "recommendations": recommend(store, index, project, symptom, case["category"])})
    store.link(project, case["id"], "raised", nid)
    if po:
        store.link(project, nid, "against_vendor", po["vendor"])
    store.audit(project, actor, "ncr.opened", {"ncr": nid, "case": case["id"], "vendor": ncr["vendor"],
                                               "precedents": [r["precedent"] for r in ncr["recommendations"]]})
    return ncr


def client_of(store, project):
    return (store.get(project, project) or {}).get("client", project)


def recommend(store, index, project, symptom, category, k=3, min_score=0.1):
    """Precedents from this client's siloed corpus only (plan §4.3/§8)."""
    hits = index.search(symptom, k=k, kind="precedent", client=client_of(store, project))
    recs = [{"precedent": pid, "score": s, "site": m.get("site"), "root_cause": m["root_cause"],
             "resolution": m["resolution"]} for s, pid, m, _ in hits if s >= min_score]
    return recs or [{"precedent": None, "score": 0, "root_cause": None,
                     "resolution": "No precedent in corpus — engineer diagnosis required"}]


def add_precedent(index, client, pid, symptom, root_cause, resolution, category, site):
    index.add(pid, f"{category} {symptom} {root_cause}", kind="precedent", client=client, category=category,
              site=site, root_cause=root_cause, resolution=resolution)


def resolve_ncr(store, index, project, ncr_id, engineer, root_cause, resolution):
    """Close the NCR and write it back into the precedent corpus (Phase 4 feedback loop)."""
    ncr = store.update(project, ncr_id, status="closed", root_cause=root_cause, resolution=resolution,
                       closed_by=engineer)
    add_precedent(index, client_of(store, project), f"{project}:{ncr_id}", ncr["symptom"], root_cause, resolution,
                  ncr["category"], project)
    store.audit(project, engineer, "ncr.resolved", {"ncr": ncr_id, "root_cause": root_cause})
    return ncr


# ---------------------------------------------------------------- as-commissioned package
def package(store, project):
    cases = store.find(project, "test_case")
    ncrs = store.find(project, "ncr")
    blockers = [c["id"] for c in cases if c["status"] != "passed"] + [n["id"] for n in ncrs if n["status"] != "closed"]
    audit_ok = store.verify_audit()
    pkg = {"project": project, "engine": ENGINE, "ready": not blockers and audit_ok, "blockers": blockers,
           "audit_chain_valid": audit_ok,
           "summary": {"cases": len(cases), "auto": sum(c["mode"] == "auto" for c in cases),
                       "manual": sum(c["mode"] == "manual" for c in cases),
                       "passed": sum(c["status"] == "passed" for c in cases),
                       "ncr_open": sum(n["status"] != "closed" for n in ncrs), "ncr_closed": sum(n["status"] == "closed" for n in ncrs)},
           "cases": [{k: c.get(k) for k in ("id", "text", "mode", "status", "results")} for c in cases],
           "ncrs": ncrs}
    return pkg


def package_markdown(pkg):
    s = pkg["summary"]
    lines = [f"# As-Commissioned Quality Package — {pkg['project']}",
             f"Status: **{'READY FOR CERTIFICATION' if pkg['ready'] else 'NOT READY'}** · audit chain "
             f"{'valid' if pkg['audit_chain_valid'] else 'BROKEN'}",
             f"Cases {s['cases']} ({s['auto']} automated / {s['manual']} manual) · passed {s['passed']} · "
             f"NCRs open {s['ncr_open']} / closed {s['ncr_closed']}", "", "| Case | Mode | Status | Evidence |", "|---|---|---|---|"]
    for c in pkg["cases"]:
        ev = c["results"][-1].get("evidence") if c["results"] else None
        lines.append(f"| {c['text']} | {c['mode']} | {c['status']} | {_evidence_text(ev)} |")
    for n in pkg["ncrs"]:
        lines += ["", f"## {n['id']} ({n['status']})", f"- Symptom: {n['symptom']}",
                  f"- Resolution: {n.get('resolution') or n['recommendations'][0]['resolution']}"]
    if pkg["blockers"]:
        lines += ["", "Blockers: " + ", ".join(pkg["blockers"])]
    return "\n".join(lines)
