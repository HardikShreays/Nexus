"""Phase 3 — Engine 3 (Commissioning Copilot), UPS system end-to-end.
Success gate: an audit-ready as-commissioned package for a real test sequence."""
import pytest

from demo import load_telemetry
from epc import commissioning as cx

P = "MUM-DC1"


@pytest.fixture
def cases(pilot):
    store, index = pilot
    tel = load_telemetry()
    return store, index, tel, {c["procedure"].split(":")[1]: c for c in cx.generate_cases(store, P, "IST-UPS", tel["points"])}


def test_split_machine_vs_engineer(cases):
    _, _, _, cs = cases
    auto = {k for k, c in cs.items() if c["mode"] == "auto"}
    assert auto == {"IST-UPS-01", "IST-UPS-03", "IST-UPS-04", "IST-DG-01", "IST-UPS-02"}
    # safety-critical / physical checks are never automated even when a number is present
    for k in ("IST-UPS-05", "IST-UPS-06", "IST-UPS-07", "IST-UPS-08"):
        assert cs[k]["mode"] == "manual"
    assert "thermograph" in cs["IST-UPS-06"]["why"]


def test_boundary_is_configurable_per_client(pilot):
    store, _ = pilot
    tel = load_telemetry()
    strict = cx.generate_cases(store, P, "IST-UPS", tel["points"], never_automate=cx.NEVER_AUTOMATE + ("transfer",))
    assert next(c for c in strict if c["procedure"].endswith("IST-UPS-01"))["mode"] == "manual"
    assert store.audit_log(P)[-1]["payload"]["never_automate"][-1] == "transfer"


def test_generated_cases_are_executable(cases):
    _, _, _, cs = cases
    auto = cs["IST-UPS-01"]
    assert auto["point"] == "ups1.transfer_time_ms" and "point = 'ups1.transfer_time_ms'" in auto["query"]
    man = cs["IST-UPS-06"]
    assert man["acceptance"] == ["hotspot < 70 °c"]
    assert any("LOTO" in s for s in man["safety"]) and man["capture"] == ["reading", "photo", "signature"]


def test_auto_execution_with_evidence(cases):
    store, index, tel, _ = cases
    res = {c["procedure"].split(":")[1]: c for c in cx.execute_auto(store, index, P, tel["readings"])}
    assert res["IST-UPS-01"]["status"] == "passed"
    assert res["IST-UPS-01"]["results"][-1]["samples"] == 3
    assert res["IST-UPS-02"]["status"] == "passed"  # worst 416.9 V is inside 415 V ±1% (410.85–419.15)
    thd = res["IST-UPS-04"]
    assert thd["status"] == "failed"
    assert thd["results"][-1]["evidence"]["value"] == 4.6 and thd["results"][-1]["violations"] == 2
    assert thd["results"][-1]["evidence"]["note"] == "required <= 3%, measured 4.6%"
    assert res["IST-DG-01"]["status"] == "no_data"  # never silently passes without evidence


def test_failure_opens_ncr_with_cited_precedent(cases):
    store, index, tel, _ = cases
    cx.execute_auto(store, index, P, tel["readings"])
    ncr = next(n for n in store.find(P, "ncr") if n["case"].endswith("IST-UPS-04"))
    top = ncr["recommendations"][0]
    assert top["precedent"] == "PUNE-DC2:NCR-014" and "firmware" in top["resolution"]
    # other clients' NCRs never leak into this client's recommendations
    assert all(r["precedent"] != "OTHER:NCR-001" for n in store.find(P, "ncr") for r in n["recommendations"])
    assert ncr["vendor"] is None  # UPS PO not loaded in this fixture


def test_cold_start_says_so(pilot):
    store, index = pilot
    recs = cx.recommend(store, index, P, "chiller compressor surge at part load", "chiller")
    assert recs[0]["precedent"] is None and "engineer diagnosis" in recs[0]["resolution"]


def test_manual_results_need_signature_and_consistent_reading(cases):
    store, index, _, cs = cases
    tid = cs["IST-UPS-06"]["id"]
    with pytest.raises(ValueError, match="signature"):
        cx.record_manual(store, index, P, tid, "eng.iyer", True, signature=None, reading=55)
    with pytest.raises(ValueError, match="contradicts"):
        cx.record_manual(store, index, P, tid, "eng.iyer", True, signature="sig:iyer", reading=82)
    c = cx.record_manual(store, index, P, tid, "eng.iyer", True, signature="sig:iyer", reading=55, photo="s3://ir/06.jpg")
    assert c["status"] == "passed" and c["results"][-1]["engineer"] == "eng.iyer"
    with pytest.raises(ValueError, match="automated"):
        cx.record_manual(store, index, P, cs["IST-UPS-01"]["id"], "eng.iyer", True, signature="x")


def test_package_blocks_until_everything_passes_then_is_audit_ready(cases):
    store, index, tel, cs = cases
    cx.execute_auto(store, index, P, tel["readings"])
    pkg = cx.package(store, P)
    assert not pkg["ready"] and "TC:IST-UPS:IST-UPS-04" in pkg["blockers"]

    # fix THD per precedent, retest, close NCRs; DG data arrives; engineers complete manual checks
    fixed = dict(tel["readings"], **{"ups1.output_voltage_thd_pct": [["2027-02-10T10:00:00", 2.2]],
                                     "dg1.start_to_load_s": [["2027-02-10T12:00:00", 8.4]]})
    cx.execute_auto(store, index, P, fixed)
    for n in store.find(P, "ncr"):
        cx.resolve_ncr(store, index, P, n["id"], "eng.iyer", "Filter caps degraded", "Replaced caps, firmware v4.2")
    for c in store.find(P, "test_case", mode="manual"):
        reading = 55 if c["procedure"].endswith("IST-UPS-06") else None
        cx.record_manual(store, index, P, c["id"], "eng.iyer", True, signature="sig:iyer", reading=reading)
    pkg = cx.package(store, P)
    assert pkg["ready"], pkg["blockers"]
    assert pkg["audit_chain_valid"] and pkg["summary"]["ncr_closed"] >= 1
    md = cx.package_markdown(pkg)
    assert "READY FOR CERTIFICATION" in md and "NCR-001" in md
