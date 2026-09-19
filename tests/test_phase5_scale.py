"""Phase 5 — multi-project rollout, access control, data governance, threshold tuning."""
import pytest

from demo import load_pilot, load_schedule_data, run_engine1
from epc import commissioning as cx
from epc import risk
from epc.platform import Platform, suggest_threshold

ACCESS = {
    "pm.shah": {"projects": ["MUM-DC1"], "roles": ["pm"]},
    "exec.rao": {"projects": "*", "roles": ["pm", "procurement", "quality"]},
    "qe.nair": {"projects": ["CHN-DC4"], "roles": ["quality"]},
}


@pytest.fixture
def portfolio():
    p = Platform(access=ACCESS)
    data = load_schedule_data()
    clients = {"MUM-DC1": "HyperscaleCo", "CHN-DC4": "HyperscaleCo", "BLR-R1": "RivalCloud"}
    for proj, client in clients.items():
        load_pilot(p.store, p.index, project=proj)
        p.store.put(proj, "project", proj, {"client": client})
        run_engine1(p.store, p.index, data["today"], project=proj)
        risk.load_schedule(p.store, proj, data)
    # CHN-DC4 has its grid connection sorted — less slip than Mumbai
    p.store.update("CHN-DC4", "G-SUB", forecast="2027-01-05")
    for proj in clients:
        p.assess(proj, data["feeds"], data["today"])
    return p


def test_access_control_is_enforced_and_audited(portfolio):
    assert portfolio.dashboard("pm.shah", "MUM-DC1", "pm")["project_slip_days"] == 20
    with pytest.raises(PermissionError):
        portfolio.dashboard("pm.shah", "CHN-DC4", "pm")          # wrong project
    with pytest.raises(PermissionError):
        portfolio.dashboard("pm.shah", "MUM-DC1", "procurement")  # wrong role
    with pytest.raises(PermissionError):
        portfolio.dashboard("stranger", "MUM-DC1", "pm")
    assert [a["actor"] for a in portfolio.store.audit_log("MUM-DC1") if a["action"] == "access.denied"] == \
        ["pm.shah", "stranger"]


def test_portfolio_rollup_respects_entitlements(portfolio):
    all_rows = portfolio.portfolio("exec.rao")
    assert [r["project"] for r in all_rows][0] in ("MUM-DC1", "BLR-R1")  # worst slip first
    assert {r["project"] for r in all_rows} == {"MUM-DC1", "CHN-DC4", "BLR-R1"}
    chn = next(r for r in all_rows if r["project"] == "CHN-DC4")
    assert chn["slip_days"] < 20
    assert [r["project"] for r in portfolio.portfolio("qe.nair")] == ["CHN-DC4"]
    assert portfolio.portfolio("stranger") == []


def test_projects_stay_isolated_in_one_platform(portfolio):
    portfolio.store.update("MUM-DC1", "V-VOLTEDGE", ncr_count=5)
    assert portfolio.store.get("CHN-DC4", "V-VOLTEDGE").get("ncr_count", 0) == 0
    assert len(portfolio.store.find("MUM-DC1", "finding")) == len(portfolio.store.find("BLR-R1", "finding"))


def test_precedents_siloed_per_client_by_default(portfolio):
    """RivalCloud's project must never be served HyperscaleCo's failure history (and vice versa)."""
    rival = cx.recommend(portfolio.store, portfolio.index, "BLR-R1", "UPS output voltage THD above 3 %", "ups")
    assert rival[0]["precedent"] == "OTHER:NCR-001"
    ours = cx.recommend(portfolio.store, portfolio.index, "CHN-DC4", "UPS output voltage THD above 3 %", "ups")
    assert all(r["precedent"] != "OTHER:NCR-001" for r in ours)


def _reviewed(store, project, n, decision):
    for i in range(n):
        store.put(project, "finding", f"F:x:{i}", {"method": "rule", "status": "compliant", "auto_cleared": False,
                                                   "review": decision, "confidence": 0.2 + i * 0.001})


def test_threshold_only_loosens_with_evidence():
    p = Platform()
    assert suggest_threshold(p.store, "P") == 0.3                       # no data -> keep conservative
    _reviewed(p.store, "P", 19, "accept")
    assert suggest_threshold(p.store, "P") == 0.3                       # not enough samples
    _reviewed(p.store, "P", 25, "accept")
    assert suggest_threshold(p.store, "P") == 0.2                       # humans agreed every time
    p.store.put("P", "finding", "F:bad", {"method": "rule", "status": "compliant", "auto_cleared": False,
                                          "review": "reject_bid_item", "confidence": 0.5})
    assert suggest_threshold(p.store, "P") == 0.3                       # one disagreement -> don't loosen
