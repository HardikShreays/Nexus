"""Phase 2 — Engine 2 (Predictive Schedule & Supply-Chain Risk). Success gate: backtest recall + lead time."""
import copy

import pytest

from demo import load_schedule_data, run_engine1
from epc import risk

P = "MUM-DC1"


@pytest.fixture
def world(pilot):
    store, index = pilot
    data = load_schedule_data()
    run_engine1(store, index, data["today"])
    risk.load_schedule(store, P, data)
    return store, data


def by_act(summary):
    return {r["activity"]: r for r in summary["activities"]}


def test_each_sub_agent_emits_expected_signal(world):
    store, data = world
    out = by_act(risk.assess(store, P, data["feeds"], data["today"]))
    src = {a: {s["source"]: s["delay_days"] for s in r["signals"]} for a, r in out.items()}
    assert src["A-100"]["procurement"] == 15        # VoltEdge realistic lead time > committed 14 wks
    assert src["A-100"]["workforce"] == 5            # 24/30 electricians on a 20-day activity
    assert src["A-100"]["macro:shortage"] == 10
    assert src["A-110"]["logistics"] == 6            # ETA + 14d JNPT congestion + 3d customs
    assert src["A-200"]["grid"] == 20                # substation 20 days late
    assert "A-120" not in [a for a, s in src.items() if s]  # at-site PO, enough crew -> no signal


def test_only_procurement_and_workforce_agents(world):
    """Plan: Phase 2 starts with these two; others are added once fusion is validated."""
    store, data = world
    out = risk.assess(store, P, data["feeds"], data["today"], agents=[risk.procurement_agent, risk.workforce_agent])
    assert {s["source"] for r in out["activities"] for s in r["signals"]} == {"procurement", "workforce"}


def test_critical_path_propagation(world):
    store, data = world
    out = risk.assess(store, P, data["feeds"], data["today"])
    a = by_act(out)
    assert a["A-200"]["slip_days"] == 20             # zero float
    assert a["A-100"]["slip_days"] == 10             # 15 own delay - 5 float
    assert a["A-110"]["slip_days"] == 0 and not a["A-110"]["critical"]  # 6 days absorbed by 10 float
    assert a["A-300"]["inherited_delay"] == 20 and a["A-400"]["slip_days"] == 20
    assert a["A-300"]["driven_by"] == "A-200" and a["A-200"]["driven_by"] is None  # root cause, not symptom
    assert out["project_slip_days"] == 20
    assert out["activities"][0]["slip_days"] == 20   # ranked worst first
    assert "A-110" in out["flagged"]                 # not critical, but high enough risk to watch
    assert "A-120" not in out["flagged"]


def test_mitigations_ranked_and_actionable(world):
    store, data = world
    a = by_act(risk.assess(store, P, data["feeds"], data["today"]))
    grid = a["A-200"]["mitigations"][0]
    assert "DG" in grid["action"] and grid["covers_slip"] and grid["cost_inr"] == 20 * risk.DG_RENTAL_INR_PER_DAY
    ups = a["A-100"]["mitigations"]
    assert ups[0]["covers_slip"] and len({m["action"] for m in ups}) == len(ups)  # no duplicates
    assert all(m["spec_compliant"] for m in ups)
    assert [m["covers_slip"] for m in ups] == sorted([m["covers_slip"] for m in ups], reverse=True)


def test_vendor_switch_only_to_engine1_compliant_vendor(world):
    store, data = world
    # Earlier in the project: UPS PO not yet issued and need-by far out -> switching is worth it.
    store.update(P, "PO-UPS-1", issued=None, committed_weeks=40, need_by="2026-12-15")
    a = by_act(risk.assess(store, P, data["feeds"], "2026-06-01"))
    switches = [m for m in a["A-100"]["mitigations"] if m["action"].startswith("Switch")]
    assert [m["action"] for m in switches] == ["Switch PO-UPS-1 to V-GRIDSAFE"]  # never AmpCore (non-compliant)
    assert switches[0]["days_saved"] > 0 and switches[0]["cost_pct"] == pytest.approx(8.0, abs=0.1)
    assert switches[0]["evidence"] == "R:BID-GRIDSAFE"


def test_risk_register_and_audit(world):
    store, data = world
    out = risk.assess(store, P, data["feeds"], data["today"])
    reg = store.find(P, "risk")
    assert {r["activity"] for r in reg} == set(out["flagged"])
    assert store.neighbors(P, f"RISK:A-200:{data['today']}", "threatens") == ["A-200"]
    assert store.audit_log(P)[-1]["action"] == "risk.assessment"


def test_backtest_success_gate(world):
    """Would the engine have flagged the delays that really happened, with weeks of lead time?"""
    store, data = world
    out = risk.assess(store, P, data["feeds"], data["today"])
    actual = {"A-100": {"slip_days": 12, "occurred_on": "2026-11-24"},
              "A-200": {"slip_days": 18, "occurred_on": "2027-01-05"},
              "A-120": {"slip_days": 0, "occurred_on": "2026-12-10"}}
    bt = risk.backtest(out, actual)
    assert bt["recall"] == 1.0 and bt["missed"] == []
    assert bt["min_lead_days"] >= 14  # weeks, not days (plan §9 KPI)


def test_backtest_reports_misses():
    bt = risk.backtest({"as_of": "2026-09-19", "flagged": []}, {"A-1": {"slip_days": 3, "occurred_on": "2026-10-01"}})
    assert bt["recall"] == 0 and bt["missed"] == ["A-1"]


def test_schedule_loop_detected(pilot):
    store, _ = pilot
    data = copy.deepcopy(load_schedule_data())
    data["activities"][0]["preds"] = ["A-400"]  # A-400 -> A-100 -> ... -> A-400
    risk.load_schedule(store, P, data)
    with pytest.raises(ValueError, match="loop"):
        risk.assess(store, P, data["feeds"], data["today"])
