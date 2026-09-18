"""Phase 1 — Engine 1 (Verification). Success gate: zero false negatives on seeded known deviations."""
import pytest

from epc import verification as v

P = "MUM-DC1"
AS_OF = "2026-09-19"

# Ground truth a compliance engineer would produce by hand for the AmpCore bid (plan: "test against
# past project data where the right answer is already known").
AMPCORE_KNOWN = {
    "TENDER:T-UPS-01": "deviation",   # 450 kVA vs 500 kVA
    "TENDER:T-UPS-02": "deviation",   # 400 V ±2% vs 415 V ±1%
    "TENDER:T-UPS-03": "deviation",   # 95 % vs >= 96 %
    "TENDER:T-UPS-04": "deviation",   # 8 ms vs <= 4 ms
    "TENDER:T-UPS-05": "compliant",   # 10 min
    "TENDER:T-UPS-06": "deviation",   # N vs N+1
    "TENDER:T-UPS-07": "missing",     # no IEC 62040-3
    "CEA-2026:CEA-UPS-01": "missing",  # THD not stated
    "CEA-2026:CEA-UPS-02": "deviation",  # 0.97 vs >= 0.99
}


def run(pilot, bid):
    store, index = pilot
    return store, v.verify_bid(store, index, P, bid, "TENDER", as_of=AS_OF)


def status(store, bid):
    return {f["requirement"]: f["status"] for f in store.find(P, "finding", bid=bid)}


def test_known_deviations_no_false_negatives(pilot):
    store, report = run(pilot, "BID-AMPCORE")
    got = status(store, "BID-AMPCORE")
    for req, expected in AMPCORE_KNOWN.items():
        assert got[req] == expected, (req, got[req])
    # nothing non-compliant may ever be auto-cleared
    assert not any(f["auto_cleared"] for f in store.find(P, "finding", bid="BID-AMPCORE") if f["status"] != "compliant")


def test_compliant_bid_clears(pilot):
    store, report = run(pilot, "BID-GRIDSAFE")
    got = status(store, "BID-GRIDSAFE")
    assert all(s == "compliant" for r, s in got.items() if r != "TENDER:T-UPS-08"), got
    assert got["TENDER:T-UPS-08"] == "needs_review"  # qualitative clause -> human, never auto
    assert report["counts"]["deviation"] == report["counts"]["missing"] == 0


def test_named_quantity_never_stands_in_for_another():
    thd = {"param": "input current total harmonic distortion", "op": "<=", "value": 3.0, "unit": "%",
           "dim": "ratio", "base": 3.0, "tol_pct": 0}
    eff = {"param": "efficiency load50pct", "op": "=", "value": 2.5, "unit": "%", "dim": "ratio", "base": 2.5,
           "tol_pct": 0}
    assert v._pick(thd, [eff]) is None


@pytest.mark.parametrize("op,spec,bid,tol_s,tol_b,ok", [
    (">=", 96, 96.5, 0, 0, True), (">=", 96, 95, 0, 0, False),
    ("<=", 4, 4, 0, 0, True), ("<=", 4, 8, 0, 0, False),
    ("=", 415, 419, 1, 0, True), ("=", 415, 420, 1, 0, False),
    ("=", 415, 415, 1, 2, False),  # bid tolerance wider than spec
    ("=", 500, 500, 0, 0, True), ("=", 500, 450, 0, 0, False),
])
def test_compare_rules(op, spec, bid, tol_s, tol_b, ok):
    mk = lambda val, tol: {"param": "p", "op": op, "value": val, "unit": "v", "dim": "voltage", "base": val,  # noqa
                           "tol_pct": tol}
    assert v.compare(mk(spec, tol_s), mk(bid, tol_b))[0] is ok


def test_unit_conversion_in_comparison():
    spec = {"param": "capacity", "op": "=", "value": 500, "unit": "kva", "dim": "apparent", "base": 500e3, "tol_pct": 0}
    bid = {"param": "capacity", "op": "=", "value": 0.5, "unit": "mva", "dim": "apparent", "base": 500e3, "tol_pct": 0}
    assert v.compare(spec, bid)[0]


def test_policy_version_in_effect_is_used(pilot):
    """CEA tightened THD from 5 % to 3 % on 2026-04-01; each check must run against the version then in force."""
    store, index = pilot
    old = v.verify_bid(store, index, P, "BID-VOLTEDGE", "TENDER", as_of="2025-06-01")
    assert old["policy_versions"] == {"CEA-2025": "2025.1"}
    new = v.verify_bid(store, index, P, "BID-VOLTEDGE", "TENDER", as_of=AS_OF)
    assert new["policy_versions"] == {"CEA-2026": "2026.1"}
    thd = store.get(P, "F:BID-VOLTEDGE:CEA-2026:CEA-UPS-01")
    assert thd["status"] == "compliant" and "<= 3%" in thd["checks"][0]["note"]
    audit = [a for a in store.audit_log(P) if a["action"] == "verification.report"]
    assert audit[-1]["payload"]["policy_versions"] == {"CEA-2026": "2026.1"}
    assert audit[-1]["payload"]["engine"] == v.ENGINE


def test_fulfilment_scoring(pilot):
    store, _ = pilot
    fast_unreliable = v.fulfilment_score(store, P, "V-VOLTEDGE", "ups", 14)
    reliable = v.fulfilment_score(store, P, "V-GRIDSAFE", "ups", 18)
    unknown = v.fulfilment_score(store, P, "V-NOBODY", "ups", 16)
    assert reliable["score"] > unknown["score"] > fast_unreliable["score"]
    assert fast_unreliable["expected_weeks"] > 14  # realistic lead time longer than promised
    store.update(P, "V-GRIDSAFE", ncr_count=2)
    assert v.fulfilment_score(store, P, "V-GRIDSAFE", "ups", 18)["score"] < reliable["score"]


def test_review_queue_and_overrides_are_audited(pilot):
    store, report = run(pilot, "BID-AMPCORE")
    queue = v.review_queue(store, P)
    assert queue and queue[0]["severity"] == "high"
    with pytest.raises(ValueError):
        v.review(store, P, queue[0]["id"], "qe.rao", "override")  # needs a justification
    f = v.review(store, P, queue[0]["id"], "qe.rao", "override", "client accepted deviation via RFI-12")
    assert f["status"] == "compliant" and f["reviewer"] == "qe.rao"
    assert store.audit_log(P)[-1]["payload"]["decision"] == "override"
    assert store.verify_audit()


def test_compliant_vendors_feed_engine2(pilot):
    store, index = pilot
    for b in ("BID-VOLTEDGE", "BID-AMPCORE", "BID-GRIDSAFE"):
        v.verify_bid(store, index, P, b, "TENDER", as_of=AS_OF)
    assert v.compliant_vendors(store, P, "ups") == []  # open review items block everyone
    for f in v.review_queue(store, P):
        if f["bid"] == "BID-GRIDSAFE":
            v.review(store, P, f["id"], "qe.rao", "override" if f["status"] != "compliant" else "accept", "FAT witnessed")
    assert [r["vendor"] for r in v.compliant_vendors(store, P, "ups")] == ["V-GRIDSAFE"]


def test_llm_verdict_recorded_but_never_auto_clears(pilot, monkeypatch):
    monkeypatch.setattr(v.llm, "judge_clause", lambda spec, bid: {"verdict": "compliant", "reason": "FAT offered",
                                                                   "model": "stub"})
    store, _ = run(pilot, "BID-VOLTEDGE")
    fat = store.get(P, "F:BID-VOLTEDGE:TENDER:T-UPS-08")
    assert fat["method"] == "llm" and fat["llm"]["model"] == "stub" and fat["status"] == "compliant"
    assert not fat["auto_cleared"] and fat["review"] == "pending"
    assert v.llm.enabled() is False  # offline by default
