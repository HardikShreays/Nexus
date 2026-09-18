"""Phase 1 — Engine 1: Specification & Quality Compliance Verification.

Requirement-driven: every applicable tender/policy clause is checked against the bid, so a
requirement the vendor silently skipped shows up as "missing" (the costliest false negative).
Numeric/standard/redundancy checks are deterministic; the LLM only weighs in on qualitative
clauses and can never auto-clear anything.
"""
from . import llm

ENGINE = "verification/1.0"
AUTO_CLEAR_MIN_CONFIDENCE = 0.3  # start conservative (plan §4.1); loosen only with measured FN/FP rates
CRITICAL_SYSTEMS = {"power", "cooling", "fire"}
LEAD_TIME_BENCHMARK_WEEKS = {"ups": 16, "generator": 24, "switchgear": 20, "transformer": 30, "chiller": 22,
                             "crah": 12, "cooling_tower": 18, "rack": 8, "pdu": 8, "fire_suppression": 10}


# ---------------------------------------------------------------- param comparison
def _jaccard(a, b):
    a, b = set(a.split()), set(b.split())
    return len(a & b) / len(a | b) if a | b else 0.0


def _pick(sp, candidates):
    """Best bid param for a spec param: same dimension, overlapping name. An unnamed quantity
    ("2 x 500 kVA" -> param "x") may stand in when it is the only one of that dimension; a
    *named* different quantity never does (efficiency 2.5 % must not satisfy THD <= 3 %)."""
    same = [c for c in candidates if c["dim"] == sp["dim"] and (sp["dim"] != "text" or c["param"] == sp["param"])]
    if not same:
        return None
    best = max(same, key=lambda c: _jaccard(sp["param"], c["param"]))
    if sp["dim"] == "text" or _jaccard(sp["param"], best["param"]) > 0:
        return best
    unnamed = [c for c in same if all(len(w) <= 2 for w in c["param"].split())]
    return unnamed[0] if len(same) == 1 and unnamed and sp["dim"] != "number" else None


def compare(sp, bp, label="bid"):
    """-> (ok: bool, note: str)"""
    if sp["dim"] == "text":
        return (sp["value"].lower() == bp["value"].lower(), f"required {sp['value']}, {label} {bp['value']}")
    x, v = sp["base"], bp["base"]
    unit = sp["unit"]
    shown = f"required {sp['op']} {sp['value']:g}{unit}" + (f" ±{sp['tol_pct']:g}%" if sp["tol_pct"] else "") + \
            f", {label} {bp['value']:g}{bp['unit']}" + (f" ±{bp['tol_pct']:g}%" if bp.get("tol_pct") else "")
    ok = {">=": v >= x - 1e-9, "<=": v <= x + 1e-9, ">": v > x, "<": v < x}.get(sp["op"])
    if ok is None:  # "=" with optional tolerance band
        ok = abs(v - x) <= abs(x) * sp["tol_pct"] / 100 + 1e-9 * max(1, abs(x))
        if ok and sp["tol_pct"] and bp.get("tol_pct", 0) > sp["tol_pct"]:
            return False, shown + " (bid tolerance wider than spec)"
    return ok, shown


def check_requirement(req, bid_clause, all_bid_params):
    """Deterministic check of one requirement clause against its matched bid clause."""
    checks = []
    local = bid_clause["params"] if bid_clause else []
    for sp in req["params"]:
        # standards / tier may be declared anywhere in the bid (compliance section), numbers must be local
        pool = all_bid_params if sp["param"] in ("standard", "tier") else local
        if sp["param"] == "standard":
            bp = next((b for b in pool if b["param"] == "standard" and b["value"].lower() == sp["value"].lower()), None)
        else:
            bp = _pick(sp, pool)
        if bp is None:
            checks.append({"param": sp["param"], "ok": None, "note": f"not stated in bid (required {sp['op']} {sp['value']})"})
        else:
            ok, note = compare(sp, bp)
            checks.append({"param": sp["param"], "ok": ok, "note": note})
    return checks


# ---------------------------------------------------------------- engine
def applicable_policies(store, project, as_of):
    """Latest version per policy source effective on `as_of` (ISO date) — audit defensibility, plan §8."""
    latest = {}
    for d in store.find(project, "document", doc_type="policy"):
        if d.get("effective", "0000") <= as_of:
            key = d.get("source", d["id"])
            if key not in latest or d["effective"] > latest[key]["effective"]:
                latest[key] = d
    return sorted(latest.values(), key=lambda d: d["id"])


def verify_bid(store, index, project, bid_doc, tender_doc, as_of="9999-12-31",
               threshold=AUTO_CLEAR_MIN_CONFIDENCE, actor="engine1"):
    bid = store.get(project, bid_doc)
    scope = set(bid.get("scope") or [])
    policies = applicable_policies(store, project, as_of)
    reqs = [c for doc in [tender_doc] + [p["id"] for p in policies]
            for c in (store.get(project, cid) for cid in store.neighbors(project, doc, "contains"))
            if not scope or c["category"] in scope]
    bid_clauses = {c: store.get(project, c) for c in store.neighbors(project, bid_doc, "contains")}
    all_bid_params = [p for c in bid_clauses.values() for p in c["params"]]

    findings = []
    for req in reqs:
        hits = index.search(req["text"], k=3, project=project, doc=bid_doc)
        best, best_checks, conf = None, [], 0.0
        for score, cid, _, _ in hits:
            checks = check_requirement(req, bid_clauses[cid], all_bid_params)
            found = sum(c["ok"] is not None for c in checks)
            if best is None or found > sum(c["ok"] is not None for c in best_checks):
                best, best_checks, conf = bid_clauses[cid], checks, score
        if best is None:
            best_checks = check_requirement(req, None, all_bid_params)
        verdict, method = None, "rule"
        if not req["params"]:
            method = "none"
            verdict = llm.judge_clause(req["text"], best and best["text"])
            status = {"compliant": "compliant", "deviation": "deviation"}.get((verdict or {}).get("verdict"), "needs_review")
            method = "llm" if verdict else method
        elif any(c["ok"] is False for c in best_checks):
            status = "deviation"
        elif all(c["ok"] is None for c in best_checks):
            status = "missing"
        elif any(c["ok"] is None for c in best_checks):
            status = "partial"
        else:
            status = "compliant"
        regulatory = req["doc_type"] == "policy"
        severity = {"deviation": "high" if regulatory or req["system"] in CRITICAL_SYSTEMS else "medium",
                    "missing": "high" if regulatory else "medium", "partial": "medium",
                    "needs_review": "low", "compliant": "none"}[status]
        auto = status == "compliant" and method == "rule" and conf >= threshold
        fid = f"F:{bid_doc}:{req['id']}"
        f = store.put(project, "finding", fid, {
            "bid": bid_doc, "vendor": bid.get("vendor"), "requirement": req["id"], "requirement_text": req["text"],
            "source": req["doc"], "regulatory": regulatory, "category": req["category"],
            "bid_clause": best and best["id"], "bid_text": best and best["text"], "checks": best_checks,
            "status": status, "severity": severity, "confidence": conf, "method": method, "llm": verdict,
            "auto_cleared": auto, "review": "n/a" if auto else "pending"})
        store.link(project, bid_doc, "has_finding", fid)
        store.link(project, fid, "against", req["id"])
        findings.append(f)

    lead = next((p["base"] / 7 for p in all_bid_params if p["dim"] == "duration"), None)
    category = next(iter(sorted(scope)), "general")
    ful = fulfilment_score(store, project, bid.get("vendor"), category, lead)
    counts = {s: sum(f["status"] == s for f in findings) for s in
              ("compliant", "partial", "deviation", "missing", "needs_review")}
    compliance = counts["compliant"] / len(findings) if findings else 0.0
    report = store.put(project, "verification_report", f"R:{bid_doc}", {
        "bid": bid_doc, "vendor": bid.get("vendor"), "tender": tender_doc, "category": category,
        "price": bid.get("price"), "lead_weeks": lead, "counts": counts, "compliance_ratio": round(compliance, 3),
        "fulfilment": ful, "vendor_risk": round(1 - compliance * ful["score"], 3),
        "findings": [f["id"] for f in findings],
        "ranked_deviations": [f["id"] for f in sorted(findings, key=_rank) if f["status"] != "compliant"],
        "policy_versions": {p["id"]: p.get("version") for p in policies}})
    if bid.get("vendor"):
        store.link(project, bid["vendor"], "submitted", bid_doc)
    store.audit(project, actor, "verification.report", {
        "engine": ENGINE, "bid": bid_doc, "tender": tender_doc, "threshold": threshold,
        "policy_versions": report["policy_versions"], "llm_model": llm.MODEL if llm.enabled() else None,
        "findings": [(f["id"], f["status"], f["method"], f["confidence"], f["auto_cleared"]) for f in findings]})
    return report


def _rank(f):
    return ({"high": 0, "medium": 1, "low": 2, "none": 3}[f["severity"]], -f["regulatory"], f["id"])


def fulfilment_score(store, project, vendor_id, category, committed_weeks):
    """Confidence the vendor delivers on its committed lead time (plan §4.1 step 4)."""
    v = (vendor_id and store.get(project, vendor_id)) or {}
    bench = LEAD_TIME_BENCHMARK_WEEKS.get(category, 16)
    committed = committed_weeks or bench
    otd = v.get("on_time_rate", 0.7)  # unknown vendor -> conservative prior
    optimism = min(1.0, committed / bench)  # promising faster than the market is itself a risk
    util = v.get("utilization", 0.7)
    capacity = 1.0 if util <= 0.85 else max(0.5, 1 - (util - 0.85) * 2)
    ncr = 0.85 ** v.get("ncr_count", 0)  # Phase 4 feedback: site NCRs erode the score
    score = round(otd * optimism * capacity * ncr, 3)
    return {"score": score, "committed_weeks": committed, "benchmark_weeks": bench,
            "expected_weeks": round(committed + (1 - score) * bench * 0.5, 1),
            "factors": {"on_time_rate": otd, "optimism": round(optimism, 3), "capacity": capacity, "ncr": round(ncr, 3)}}


# ---------------------------------------------------------------- human-in-the-loop
def review_queue(store, project):
    return sorted((f for f in store.find(project, "finding") if f["review"] == "pending"), key=_rank)


def review(store, project, finding_id, reviewer, decision, note=""):
    """decision: accept (finding stands) | override (reviewer judges it compliant) | reject_bid_item"""
    if decision not in ("accept", "override", "reject_bid_item"):
        raise ValueError(decision)
    if not note and decision == "override":
        raise ValueError("override needs a justification note")  # audit defensibility
    f = store.update(project, finding_id, review=decision, reviewer=reviewer, review_note=note,
                     status="compliant" if decision == "override" else store.get(project, finding_id)["status"])
    store.audit(project, reviewer, "verification.review", {"finding": finding_id, "decision": decision, "note": note})
    return f


def compliant_vendors(store, project, category):
    """Vendors whose bid for `category` has no open non-conformance — Engine 2 mitigation candidates."""
    out = []
    for r in store.find(project, "verification_report", category=category):
        fs = [store.get(project, f) for f in r["findings"]]
        if all(f["status"] == "compliant" and (f["auto_cleared"] or f["review"] in ("accept", "override")) for f in fs):
            r = {**r, "fulfilment": fulfilment_score(store, project, r["vendor"], category, r["lead_weeks"])}
            out.append(r)
    return sorted(out, key=lambda r: r["fulfilment"]["expected_weeks"])

