"""Phase 4 — engines talk through the bus, feedback loop grows the corpora, role dashboards."""
import pytest

from demo import load_pilot, load_schedule_data, load_telemetry, run_engine1
from epc import commissioning as cx
from epc import risk, verification
from epc.platform import Platform

P = "MUM-DC1"


@pytest.fixture
def plat():
    p = Platform(*load_pilot())
    data = load_schedule_data()
    run_engine1(p.store, p.index, data["today"])
    risk.load_schedule(p.store, P, data)
    cx.generate_cases(p.store, P, "IST-UPS", load_telemetry()["points"])
    p.data = data
    return p


def a100_delay(summary):
    return next(r for r in summary["activities"] if r["activity"] == "A-100")["own_delay"]


def test_ncr_ripples_to_engine1_and_engine2(plat):
    before = plat.assess(P, plat.data["feeds"], plat.data["today"])
    score_before = verification.fulfilment_score(plat.store, P, "V-VOLTEDGE", "ups", 14)["score"]
    plat.run_commissioning(P, load_telemetry()["readings"])        # THD fails -> NCR against VoltEdge (UPS PO)
    ncr = next(n for n in plat.store.find(P, "ncr") if n["case"].endswith("IST-UPS-04"))
    assert ncr["vendor"] == "V-VOLTEDGE" and ncr["po"] == "PO-UPS-1"
    assert plat.store.get(P, "V-VOLTEDGE")["ncr_count"] >= 1                           # Engine 1 input changed
    assert verification.fulfilment_score(plat.store, P, "V-VOLTEDGE", "ups", 14)["score"] < score_before
    assert "NCR" in plat.store.get(P, "PO-UPS-1")["watch"]                              # other in-flight POs flagged
    after = plat.assess(P, plat.data["feeds"], plat.data["today"])
    assert a100_delay(after) >= a100_delay(before)                                      # Engine 2 sees more risk
    assert plat.store.neighbors(P, ncr["id"], "against_vendor") == ["V-VOLTEDGE"]      # graph edge


def test_late_equipment_puts_commissioning_on_hold(plat):
    plat.assess(P, plat.data["feeds"], plat.data["today"])
    ups_cases = plat.store.find(P, "test_case", category="ups")
    assert ups_cases and all("PO-UPS-1" in c["hold"] for c in ups_cases)
    assert plat.dashboard("pm", P, "quality")["commissioning"]["on_hold"] == len(ups_cases)


def test_resolved_ncr_becomes_precedent_for_next_project(plat):
    plat.run_commissioning(P, load_telemetry()["readings"])
    ncr = next(n for n in plat.store.find(P, "ncr") if n["case"].endswith("IST-UPS-04"))
    plat.resolve_ncr(P, ncr["id"], "eng.iyer", "Neutral bonding error at UPS output transformer",
                     "Re-terminated neutral-earth bond at output transformer; THD re-measured 1.9 %")
    # a later project for the same client hits a similar failure — our own fix is now cited
    load_pilot(plat.store, plat.index, project="MUM-DC2")
    plat.store.put("MUM-DC2", "project", "MUM-DC2", {"client": "HyperscaleCo"})
    recs = cx.recommend(plat.store, plat.index, "MUM-DC2", "UPS output voltage THD neutral bonding", "ups")
    assert recs[0]["precedent"] == f"{P}:{ncr['id']}" and recs[0]["site"] == P


def test_realized_delay_updates_vendor_and_risk_corpus(plat):
    rate = plat.store.get(P, "V-COOLAIR") or {}
    plat.realize_delay(P, "PO-CHL-1", 9, "JNPT congestion during monsoon, vessel rolled over")
    v = plat.store.get(P, "V-COOLAIR")
    assert v["on_time_rate"] < rate.get("on_time_rate", 0.7)
    hits = plat.similar_risks(P, "chiller shipment port congestion")
    assert hits and hits[0][1] == f"{P}:DELAY:PO-CHL-1" and hits[0][3] == 9


def test_approved_vendor_switch_reverifies_substitute(plat):
    plat.store.update(P, "PO-UPS-1", issued=None, committed_weeks=40, need_by="2026-12-15")
    out = plat.assess(P, plat.data["feeds"], "2026-06-01")
    opt = next(m for r in out["activities"] if r["activity"] == "A-100" for m in r["mitigations"]
               if m["action"].startswith("Switch"))
    n_reports = sum(a["action"] == "verification.report" for a in plat.store.audit_log(P))
    plat.approve_mitigation(P, "pm.shah", "PO-UPS-1", opt, "2026-06-01")
    po = plat.store.get(P, "PO-UPS-1")
    assert po["vendor"] == "V-GRIDSAFE" and po["committed_weeks"] == 18
    log = plat.store.audit_log(P)
    assert sum(a["action"] == "verification.report" for a in log) == n_reports + 1  # compliance re-check ran
    assert any(a["action"] == "mitigation.approved" and a["actor"] == "pm.shah" for a in log)


def test_role_dashboards(plat):
    plat.assess(P, plat.data["feeds"], plat.data["today"])
    pm = plat.dashboard("u", P, "pm")
    assert pm["project_slip_days"] == 20 and pm["top_risks"][0]["activity"] == "A-200"
    assert "DG" in pm["top_risks"][0]["do"]
    ist = next(r for r in pm["top_risks"] if r["activity"] == "A-300")
    assert ist["driven_by"] == "A-200" and ist["do"] == "recover A-200 first"
    plat.assess(P, plat.data["feeds"], plat.data["today"])   # re-run must not double-count
    assert len(plat.dashboard("u", P, "pm")["top_risks"]) == len(pm["top_risks"])
    proc = plat.dashboard("u", P, "procurement")
    vendors = {v["vendor"]: v for v in proc["vendors"]}
    assert vendors["V-GRIDSAFE"]["vendor_risk"] < vendors["V-AMPCORE"]["vendor_risk"]
    q = plat.dashboard("u", P, "quality")
    assert q["review_queue"]["high"] > 0 and q["commissioning"]["total"] == 9


def test_kpis_and_event_audit_trail(plat):
    plat.assess(P, plat.data["feeds"], plat.data["today"])
    plat.run_commissioning(P, load_telemetry()["readings"])
    k = plat.kpis(P)
    assert 0 < k["bid_clauses_auto_cleared_pct"] < 100
    assert k["test_cases_automated_pct"] == pytest.approx(100 * 5 / 9, abs=0.1)
    events = {a["action"] for a in plat.store.audit_log(P)}
    assert {"event.risk.assessed", "event.ncr.opened", "event.vendor.exposure"} <= events
    assert plat.store.verify_audit()
