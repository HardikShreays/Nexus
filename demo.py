"""End-to-end demo on the sample pilot project. Run: python3 demo.py"""
import json
import pathlib

from epc import aws
from epc.commissioning import add_precedent
from epc.ingest import ingest
from epc.rag import Index
from epc.store import Store

DATA = pathlib.Path(__file__).parent / "sample_data"
P = "MUM-DC1"
BIDS = [("BID-VOLTEDGE", "bid_voltedge.md", "V-VOLTEDGE", 41_000_000),
        ("BID-AMPCORE", "bid_ampcore.md", "V-AMPCORE", 35_500_000),
        ("BID-GRIDSAFE", "bid_gridsafe.md", "V-GRIDSAFE", 44_300_000)]


def load_pilot(store=None, index=None, project=P):
    """Phase 0: ingest tender, versioned policy snapshots, bids and vendor master."""
    store, index = store or Store(), index or Index()
    read = lambda f: aws.read_doc(DATA / f)  # S3 + Textract when EPC_S3_BUCKET is set  # noqa: E731
    store.put(project, "project", project, {"name": "Mumbai DC1 — 24 MW hyperscale", "client": "HyperscaleCo"})
    ingest(store, index, project, "TENDER", read("tender.md"), "tender")
    ingest(store, index, project, "CEA-2025", read("policy_cea_2025.md"), "policy",
           source="CEA", version="2025.1", effective="2025-01-01")
    ingest(store, index, project, "CEA-2026", read("policy_cea_2026.md"), "policy",
           source="CEA", version="2026.1", effective="2026-04-01")
    for doc, f, vendor, price in BIDS:
        ingest(store, index, project, doc, read(f), "bid", vendor=vendor, scope=["ups"], price=price)
    for v in json.loads(read("vendors.json")):
        store.put(project, "vendor", v["id"], v)
    ingest(store, index, project, "IST-UPS", read("ist_ups.md"), "procedure", version="C")
    for pr in json.loads(read("precedents.json")):
        add_precedent(index, pr["client"], pr["id"], pr["symptom"], pr["root_cause"], pr["resolution"],
                      pr["category"], pr["site"])
    return store, index


def run_engine1(store, index, today, project=P, reviewer="qe.rao"):
    """Phase 1 on every bid; the quality engineer clears GridSafe's review items (FAT witnessed)."""
    from epc import verification
    reports = [verification.verify_bid(store, index, project, doc, "TENDER", as_of=today) for doc, *_ in BIDS]
    for f in verification.review_queue(store, project):
        if f["bid"] == "BID-GRIDSAFE":
            verification.review(store, project, f["id"], reviewer, "accept" if f["status"] == "compliant" else "override",
                                 "FAT witness confirmed in clarification letter CL-07")
    return reports


def load_schedule_data():
    return json.loads((DATA / "schedule.json").read_text())


def load_telemetry():
    return json.loads((DATA / "telemetry.json").read_text())


def main():
    from epc import commissioning as cx
    from epc import risk
    from epc.platform import Platform

    plat = Platform(*load_pilot())
    data, tel = load_schedule_data(), load_telemetry()
    today = data["today"]
    line = lambda t: print(f"\n=== {t} " + "=" * (70 - len(t)))  # noqa: E731

    line("Phase 1 · Engine 1 — bid verification")
    for rep in run_engine1(plat.store, plat.index, today):
        print(f"{rep['vendor']:<11} compliance {rep['compliance_ratio']:.0%}  fulfilment {rep['fulfilment']['score']:.2f}"
              f"  vendor-risk {rep['vendor_risk']:.2f}  {rep['counts']}")
        for fid in rep["ranked_deviations"][:3]:
            f = plat.store.get(P, fid)
            print(f"   [{f['severity']}] {f['status']:<9} {f['requirement_text'][:48]:<48} "
                  f"{(f['checks'] or [{'note': ''}])[0]['note']}")

    line("Phase 2 · Engine 2 — critical-path risk")
    risk.load_schedule(plat.store, P, data)
    out = plat.assess(P, data["feeds"], today)
    print(f"Project finish slip forecast: {out['project_slip_days']} days")
    for r in out["activities"]:
        if r["activity"] in out["flagged"]:
            print(f" {r['activity']} {r['name'][:36]:<36} slip {r['slip_days']:>3}d  score {r['score']:.2f}")
            for s in r["signals"]:
                print(f"     ↳ {s['source']:<15} {s['reason']}")
            for m in r["mitigations"][:2]:
                print(f"     ✔ {m['action']} — saves {m['days_saved']}d, ₹{m['cost_inr']:,}"
                      f"{' (covers slip)' if m['covers_slip'] else ''}")

    line("Phase 3 · Engine 3 — commissioning copilot")
    cases = cx.generate_cases(plat.store, P, "IST-UPS", tel["points"])
    for c in cases:
        print(f" {c['mode']:<6} {c['text'][:60]:<60} ({c['why']})")
    for c in plat.run_commissioning(P, tel["readings"]):
        print(f" → {c['id']}: {c['status']}")
    for n in plat.store.find(P, "ncr"):
        top = n["recommendations"][0]
        print(f" {n['id']} vs {n['vendor']}: {n['symptom'][:70]}\n     precedent {top['precedent']}: {top['resolution']}")

    line("Phase 4 · cross-engine effects + dashboards")
    print(" PO-UPS-1 watch:", plat.store.get(P, "PO-UPS-1").get("watch"))
    print(" VoltEdge NCR count:", plat.store.get(P, "V-VOLTEDGE").get("ncr_count"))
    for role in ("pm", "procurement", "quality"):
        print(f" {role}: {json.dumps(plat.dashboard('demo', P, role))[:300]}")
    print(" KPIs:", plat.kpis(P))

    line("As-commissioned package")
    print(cx.package_markdown(cx.package(plat.store, P)))
    print("\nAudit chain valid:", plat.store.verify_audit(), f"({len(plat.store.audit_log(P))} entries)")


if __name__ == "__main__":
    main()
