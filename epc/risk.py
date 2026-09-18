"""Phase 2 — Engine 2: Predictive Schedule & Supply-Chain Risk.

Sub-agents (procurement, logistics, workforce, grid, macro) each emit signals
{activity, source, delay_days, score, reason, po}. The fusion step combines them per activity,
propagates slip along finish-to-start links (CPM-lite) and attaches ranked mitigations — every
vendor-switch option is pulled live from Engine 1, so it is spec-compliant by construction.

ponytail: sub-agents are deterministic functions over structured feeds. An LLM sub-agent for
unstructured news/geopolitics only needs to emit the same signal dict — add it to SUB_AGENTS.
"""
import math
from datetime import date, timedelta

from . import verification

ENGINE = "risk/1.0"
FLAG_SCORE = 0.3
AIR_FREIGHT = {"days_saved_max": 18, "cost_pct": 4.0}
CREW_DAY_RATE_INR = 4_500
DG_RENTAL_INR_PER_DAY = 180_000


def d(s):
    return date.fromisoformat(s)


def _score(delay, float_days):
    return round(min(1.0, max(0.0, delay) / (float_days + 7)), 3)


def load_schedule(store, project, data):
    """Persist schedule activities, POs and grid milestones and link them in the graph."""
    for a in data["activities"]:
        store.put(project, "activity", a["id"], a)
        for p in a.get("preds", []):
            store.link(project, p, "precedes", a["id"])
        for po in a.get("pos", []):
            store.link(project, po, "feeds", a["id"])
        for g in a.get("grid", []):
            store.link(project, g, "gates", a["id"])
    for po in data["pos"]:
        store.put(project, "po", po["id"], po)
        store.link(project, po["vendor"], "supplies", po["id"])
    for g in data.get("grid_milestones", []):
        store.put(project, "grid_milestone", g["id"], g)


# ---------------------------------------------------------------- sub-agents
def procurement_agent(store, project, feeds, today):
    out = []
    for po in store.find(project, "po"):
        if po["status"] in ("in_transit", "at_site"):
            continue  # logistics agent owns shipped items
        ful = verification.fulfilment_score(store, project, po["vendor"], po["category"], po["committed_weeks"])
        start = d(po["issued"]) if po.get("issued") else today
        expected = start + timedelta(days=round(ful["expected_weeks"] * 7))
        delay = (expected - d(po["need_by"])).days
        for act in store.neighbors(project, po["id"], "feeds"):
            a = store.get(project, act)
            s = _score(delay, a["float"]) if delay > 0 else round((1 - ful["score"]) * 0.3, 3)
            out.append({"activity": act, "source": "procurement", "po": po["id"], "delay_days": max(0, delay),
                        "score": s, "reason": f"{po['id']} ({po['vendor']}) expected {expected} vs need-by "
                                              f"{po['need_by']}; fulfilment {ful['score']}"})
    return out


def logistics_agent(store, project, feeds, today):
    out = []
    for po in store.find(project, "po", status="in_transit"):
        congestion = feeds.get("port_congestion_days", {}).get(po.get("port"), 0)
        arrival = d(po["eta"]) + timedelta(days=congestion + feeds.get("customs_days", 0))
        delay = (arrival - d(po["need_by"])).days
        for act in store.neighbors(project, po["id"], "feeds"):
            a = store.get(project, act)
            out.append({"activity": act, "source": "logistics", "po": po["id"], "delay_days": max(0, delay),
                        "score": _score(delay, a["float"]),
                        "reason": f"{po['id']} ETA {po['eta']} + {congestion}d congestion at {po.get('port')} "
                                  f"-> {arrival} vs need-by {po['need_by']}"})
    return out


def workforce_agent(store, project, feeds, today):
    out = []
    avail = feeds.get("workforce", {})
    for a in store.find(project, "activity"):
        need, have = a.get("crew", 0), avail.get(a.get("trade"), math.inf)
        if need and have < need:
            delay = math.ceil(a["duration"] * (need / max(have, 1) - 1))
            out.append({"activity": a["id"], "source": "workforce", "po": None, "delay_days": delay,
                        "score": _score(delay, a["float"]), "shortfall": need - have,
                        "reason": f"{a['trade']} crew {have}/{need} -> +{delay}d on {a['duration']}d activity"})
    return out


def grid_agent(store, project, feeds, today):
    out = []
    for g in store.find(project, "grid_milestone"):
        delay = (d(g["forecast"]) - d(g["due"])).days
        for act in store.neighbors(project, g["id"], "gates"):
            a = store.get(project, act)
            out.append({"activity": act, "source": "grid", "po": None, "milestone": g["id"],
                        "delay_days": max(0, delay), "score": _score(delay, a["float"]),
                        "reason": f"{g['name']} forecast {g['forecast']} vs due {g['due']} ({g['status']})"})
    return out


def macro_agent(store, project, feeds, today):
    """Shortage / disaster / geopolitical / price signals mapped onto exposed POs."""
    out = []
    for sig in feeds.get("signals", []):
        for po in store.find(project, "po"):
            hit = po["category"] in sig.get("categories", []) or po.get("origin") in sig.get("regions", [])
            if not hit or po["status"] == "at_site":
                continue
            for act in store.neighbors(project, po["id"], "feeds"):
                a = store.get(project, act)
                delay = sig.get("delay_days", 0)
                out.append({"activity": act, "source": f"macro:{sig['kind']}", "po": po["id"], "delay_days": delay,
                            "score": round(max(_score(delay, a["float"]), sig.get("severity", 0) * 0.5), 3),
                            "cost_pct": sig.get("cost_pct", 0), "reason": f"{sig['kind']}: {sig['note']}"})
    return out


SUB_AGENTS = [procurement_agent, logistics_agent, workforce_agent, grid_agent, macro_agent]


# ---------------------------------------------------------------- fusion + CPM-lite
def assess(store, project, feeds, today, agents=SUB_AGENTS, actor="engine2"):
    today = d(today) if isinstance(today, str) else today
    signals = [s for agent in agents for s in agent(store, project, feeds, today)]
    acts = {a["id"]: a for a in store.find(project, "activity")}
    own = {}
    for aid in acts:
        sig = [s for s in signals if s["activity"] == aid]
        # ponytail: parallel causes don't add — the worst one sets the delay. Upgrade: Monte Carlo on delay distributions.
        own[aid] = {"delay": max((s["delay_days"] for s in sig), default=0),
                    "score": round(1 - math.prod(1 - s["score"] for s in sig), 3), "signals": sig}

    slip = {}

    def resolve(aid, seen=()):
        if aid in slip:
            return slip[aid]
        if aid in seen:
            raise ValueError(f"schedule loop at {aid}")
        preds = [(resolve(p, seen + (aid,)), p) for p in store.neighbors(project, aid, "precedes", reverse=True)]
        incoming, driver = max(preds, default=(0, None))
        slip[aid] = max(0, max(own[aid]["delay"], incoming) - acts[aid]["float"])
        own[aid]["inherited"] = incoming
        own[aid]["driver"] = driver if incoming > own[aid]["delay"] else None
        return slip[aid]

    results = []
    for aid, a in acts.items():
        s = resolve(aid)
        r = {"activity": aid, "name": a["name"], "float": a["float"], "own_delay": own[aid]["delay"],
             "inherited_delay": own[aid]["inherited"], "driven_by": own[aid]["driver"], "slip_days": s, "critical": s > 0,
             "score": own[aid]["score"],
             "signals": own[aid]["signals"]}
        r["mitigations"] = mitigations(store, project, r, feeds, today) if r["own_delay"] > 0 else []
        results.append(r)
    results.sort(key=lambda r: (-r["slip_days"], -r["score"], r["activity"]))

    ends = [aid for aid in acts if not store.neighbors(project, aid, "precedes")]
    summary = {"as_of": str(today), "project_slip_days": max((slip[a] for a in ends), default=0),
               "flagged": [r["activity"] for r in results if r["critical"] or r["score"] >= FLAG_SCORE],
               "activities": results}
    for old in store.find(project, "risk", status="open"):  # the register shows the latest run only
        store.update(project, old["id"], status="superseded")
    for r in results:
        if r["activity"] in summary["flagged"]:
            store.put(project, "risk", f"RISK:{r['activity']}:{today}", {
                "activity": r["activity"], "as_of": str(today), "slip_days": r["slip_days"], "score": r["score"],
                "sources": sorted({s["source"] for s in r["signals"]}), "driven_by": r["driven_by"],
                "top_mitigation": (r["mitigations"] or [None])[0],
                "status": "open"})
            store.link(project, f"RISK:{r['activity']}:{today}", "threatens", r["activity"])
    store.audit(project, actor, "risk.assessment", {"engine": ENGINE, "as_of": str(today),
                                                    "project_slip_days": summary["project_slip_days"],
                                                    "flagged": summary["flagged"]})
    return summary


# ---------------------------------------------------------------- mitigations
def mitigations(store, project, r, feeds, today):
    """Ranked options with cost/time trade-offs. Rank: covers the slip first, then cost per day saved."""
    opts, need = [], r["own_delay"]
    for sig in r["signals"]:
        po = sig.get("po") and store.get(project, sig["po"])
        if sig["source"] in ("procurement",) or sig["source"].startswith("macro"):
            if po and po["status"] not in ("in_transit", "at_site"):
                current = d(po["need_by"]) + timedelta(days=sig["delay_days"])  # forecast arrival today
                for alt in verification.compliant_vendors(store, project, po["category"]):
                    if alt["vendor"] == po["vendor"]:
                        continue
                    arrival = today + timedelta(days=round(alt["fulfilment"]["expected_weeks"] * 7))
                    saved = (current - arrival).days
                    if saved > 0:
                        premium = round((alt["price"] - po["value"]) / po["value"] * 100, 1) if alt.get("price") else None
                        opts.append({"action": f"Switch {po['id']} to {alt['vendor']}", "days_saved": saved,
                                     "cost_inr": max(0, (alt["price"] or 0) - po["value"]), "cost_pct": premium,
                                     "spec_compliant": True, "evidence": alt["id"]})
                opts.append({"action": f"Expedite fabrication at {po['vendor']} (priority slot)",
                             "days_saved": min(sig["delay_days"], 10), "cost_inr": round(po["value"] * 0.03),
                             "cost_pct": 3.0, "spec_compliant": True})
        elif sig["source"] == "logistics" and po:
            saved = min(sig["delay_days"] + 1, AIR_FREIGHT["days_saved_max"])
            opts.append({"action": f"Air-freight / priority clearance for {po['id']}", "days_saved": saved,
                         "cost_inr": round(po["value"] * AIR_FREIGHT["cost_pct"] / 100),
                         "cost_pct": AIR_FREIGHT["cost_pct"], "spec_compliant": True})
        elif sig["source"] == "workforce":
            a = store.get(project, r["activity"])
            opts.append({"action": f"Mobilise {sig['shortfall']} extra {a['trade']} crew (second contractor)",
                         "days_saved": sig["delay_days"],
                         "cost_inr": sig["shortfall"] * CREW_DAY_RATE_INR * a["duration"], "spec_compliant": True})
        elif sig["source"] == "grid":
            opts.append({"action": "Temporary DG power so IST can proceed ahead of DISCOM energisation",
                         "days_saved": sig["delay_days"], "cost_inr": sig["delay_days"] * DG_RENTAL_INR_PER_DAY,
                         "spec_compliant": True, "note": "needs client + CEA safety approval"})
    best = {}
    for o in opts:  # two signals on one PO propose the same action — keep the stronger one
        if o["action"] not in best or o["days_saved"] > best[o["action"]]["days_saved"]:
            best[o["action"]] = o
    opts = list(best.values())
    for o in opts:
        o["covers_slip"] = o["days_saved"] >= need - r["float"]
        o["inr_per_day"] = round(o["cost_inr"] / max(o["days_saved"], 1))
    return sorted(opts, key=lambda o: (not o["covers_slip"], o["inr_per_day"]))


# ---------------------------------------------------------------- backtest (Phase 2 success gate)
def backtest(summary, actual):
    """actual: {activity: {"slip_days": n, "occurred_on": iso}}. Did we flag every real slip, early?"""
    real = {a for a, x in actual.items() if x["slip_days"] > 0}
    caught = real & set(summary["flagged"])
    lead = {a: (d(actual[a]["occurred_on"]) - d(summary["as_of"])).days for a in caught}
    return {"recall": len(caught) / len(real) if real else 1.0, "missed": sorted(real - caught),
            "false_alarms": sorted(set(summary["flagged"]) - real), "lead_days": lead,
            "min_lead_days": min(lead.values(), default=None)}
