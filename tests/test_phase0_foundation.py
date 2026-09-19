"""Phase 0 — ingestion, taxonomy, storage, graph, vector index, audit trail."""
import sqlite3

import pytest

from epc.ingest import classify, extract_params
from epc.rag import Index
from epc.store import Store

P = "MUM-DC1"


def params(text, **kw):
    return {(p["param"], p["op"], p["value"], p.get("unit")) for p in extract_params(text, **kw)}


@pytest.mark.parametrize("text,expected", [
    ("Output voltage 415 V ±1%", ("output voltage", "=", 415.0, "v")),
    ("Transfer time shall not exceed 4 ms", ("transfer time", "<=", 4.0, "ms")),
    ("Battery autonomy minimum 10 min at full load", ("battery autonomy", ">=", 10.0, "min")),
    ("Efficiency at 50% load >= 96 %", ("efficiency load50pct", ">=", 96.0, "%")),
    ("Noise level max 85 dBA at 1 m", ("noise level", "<=", 85.0, "dba")),
    ("Input power factor >= 0.99", ("input power factor", ">=", 0.99, "")),
    ("Delivery within 14 weeks from PO", ("delivery", "<=", 14.0, "weeks")),
])
def test_extract_numeric(text, expected):
    assert expected in params(text)


def test_extract_text_params_and_tolerance():
    ps = extract_params("UPS modules in N+1 redundancy, comply with IEC 62040-3, Tier III")
    got = {(p["param"], p["value"]) for p in ps}
    assert {("redundancy", "N+1"), ("standard", "IEC 62040-3"), ("tier", "tieriii")} <= got
    assert extract_params("Output voltage 415 V ±1%")[0]["tol_pct"] == 1.0


def test_units_normalised_to_base():
    kva = extract_params("capacity 500 kVA")[0]
    mva = extract_params("capacity 0.5 MVA")[0]
    assert kva["dim"] == mva["dim"] == "apparent" and kva["base"] == mva["base"] == 500_000


def test_standard_numbers_and_bare_numbers_are_not_requirements():
    assert all(p["param"] != "iec" for p in extract_params("Comply with IEC 62040-3"))
    assert extract_params("Project phase 3 of 2026") == []
    assert ("power factor", "=", 0.99, "") in params("power factor 0.99", lenient=True)


def test_taxonomy_classification():
    assert classify("Chiller cooling capacity 1000 TR") == ("cooling", "chiller")
    assert classify("Transfer time 2 ms", hint="UPS") == ("power", "ups")
    assert classify("Painting of walls") == ("general", "general")


def test_ingest_builds_graph_index_and_audit(pilot):
    store, index = pilot
    clauses = store.neighbors(P, "TENDER", "contains")
    assert len(clauses) == 11
    ups = store.get(P, "TENDER:T-UPS-04")
    assert ups["category"] == "ups" and ups["params"][0]["op"] == "<="
    hit = index.search("UPS transfer time", k=1, project=P, doc="TENDER")[0]
    assert hit[1] == "TENDER:T-UPS-04"
    assert store.get(P, "TENDER")["sha256"]
    assert any(a["action"] == "document.ingested" for a in store.audit_log(P))


def test_tenant_isolation():
    store, index = Store(), Index()
    store.put("A", "vendor", "V1", {"name": "secret A"})
    index.add("a1", "UPS transfer time 2 ms", project="A")
    index.add("b1", "UPS transfer time 3 ms", project="B")
    assert store.get("B", "V1") is None and store.find("B", "vendor") == []
    assert [h[1] for h in index.search("UPS transfer", project="B")] == ["b1"]


def test_audit_is_append_only_and_tamper_evident():
    store = Store()
    store.audit(P, "alice", "x", {"a": 1})
    store.audit(P, "bob", "y", {"b": 2})
    assert store.verify_audit()
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE audit SET actor='mallory'")
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("DELETE FROM audit")
    # bypass the triggers (a DBA with raw access) — the hash chain still catches it
    store.db.execute("DROP TRIGGER audit_no_update")
    store.db.execute("UPDATE audit SET payload='{\"a\": 99}' WHERE seq=1")
    assert not store.verify_audit()
