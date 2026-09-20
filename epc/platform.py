"""Phase 4 — integration: event bus between engines, feedback loop, role dashboards.
Phase 5 — scale & harden: multi-project portfolio with access control, threshold tuning.

ponytail: in-process pub/sub, plus an EventBridge PutEvents per emit when EPC_EVENT_BUS is
set. Handlers stay in-process here; the bus is what a Lambda or Step Functions target hooks
onto when an engine moves out of this deployment — handler signatures stay the same.
"""
from collections import defaultdict

from . import aws, commissioning, risk, verification
from .rag import Index
from .store import Store


class Platform:
    def __init__(self, store=None, index=None, access=None):
        self.store, self.index = store or Store(), index or Index()
        self.access = access  # {user: {"projects": [...] or "*", "roles": [...]}}; None = single-tenant dev mode
        self.handlers = defaultdict(list)
        for event, fn in [("ncr.opened", self._ncr_hits_vendor), ("risk.assessed", self._resequence_commissioning),
                          ("risk.realized", self._learn_from_delay), ("mitigation.approved", self._apply_mitigation)]:
            self.on(event, fn)

    # ------------------------------------------------------------ bus
    def on(self, event, fn):
        self.handlers[event].append(fn)

    def emit(self, project, event, payload):
        self.store.audit(project, "bus", f"event.{event}", payload)
        aws.put_event(project, event, payload)
        for fn in self.handlers[event]:
            fn(project, payload)

    # ------------------------------------------------------------ engine entry points (emit events)
    def verify_bid(self, project, bid, tender, as_of):
        rep = verification.verify_bid(self.store, self.index, project, bid, tender, as_of=as_of)
        self.emit(project, "bid.verified", {"bid": bid, "vendor": rep["vendor"], "risk": rep["vendor_risk"]})
        return rep

    def assess(self, project, feeds, today):
        out = risk.assess(self.store, project, feeds, today)
        self.emit(project, "risk.assessed", {"as_of": out["as_of"], "flagged": out["flagged"],
                                             "late_pos": _late_pos(out)})
        return out

    def run_commissioning(self, project, readings):
        return self._with_ncr_events(project, commissioning.execute_auto, self.store, self.index, project, readings)

    def record_manual(self, project, *args, **kw):
        return self._with_ncr_events(project, commissioning.record_manual, self.store, self.index, project, *args, **kw)

    def resolve_ncr(self, project, ncr_id, engineer, root_cause, resolution):
        ncr = commissioning.resolve_ncr(self.store, self.index, project, ncr_id, engineer, root_cause, resolution)
        self.emit(project, "ncr.resolved", {"ncr": ncr_id, "vendor": ncr["vendor"]})
        return ncr

    def _with_ncr_events(self, project, fn, *args, **kw):
        before = {n["id"] for n in self.store.find(project, "ncr")}
        out = fn(*args, **kw)
        for n in self.store.find(project, "ncr"):
            if n["id"] not in before:
                self.emit(project, "ncr.opened", {"ncr": n["id"], "vendor": n["vendor"], "category": n["category"]})
        return out

    # ------------------------------------------------------------ cross-engine handlers
    def _ncr_hits_vendor(self, project, e):
        """Engine 3 NCR -> Engine 1 vendor score drops -> Engine 2 re-checks that vendor's other in-flight POs."""
        if not e["vendor"]:
            return
        v = self.store.get(project, e["vendor"]) or {"name": e["vendor"]}
        self.store.put(project, "vendor", e["vendor"], {**v, "ncr_count": v.get("ncr_count", 0) + 1})
        exposed = [po["id"] for po in self.store.find(project, "po", vendor=e["vendor"]) if po["status"] != "at_site"]
        for po in exposed:
            self.store.update(project, po, watch=f"vendor NCR {e['ncr']} — inspect before dispatch")
        self.emit(project, "vendor.exposure", {"vendor": e["vendor"], "ncr": e["ncr"], "pos": exposed})

    def _resequence_commissioning(self, project, e):
        """Engine 2 late equipment -> Engine 3 holds the affected test cases so engineers aren't rostered."""
        for po_id, eta in e["late_pos"].items():
            po = self.store.get(project, po_id)
            for c in self.store.find(project, "test_case", category=po["category"]):
                if c["status"] != "passed":
                    self.store.update(project, c["id"], hold=f"awaiting {po_id} (forecast {eta})")

    def _learn_from_delay(self, project, e):
        """Realised delay -> vendor on-time rate (EWMA) + risk precedent corpus."""
        po = self.store.get(project, e["po"])
        v = self.store.get(project, po["vendor"]) or {}
        on_time = 1.0 if e["delay_days"] <= 0 else 0.0
        rate = round(0.8 * v.get("on_time_rate", 0.7) + 0.2 * on_time, 3)
        self.store.put(project, "vendor", po["vendor"], {**v, "on_time_rate": rate})
        self.index.add(f"{project}:DELAY:{e['po']}", f"{po['category']} {e['cause']}", kind="risk_precedent",
                       client=commissioning.client_of(self.store, project), category=po["category"],
                       delay_days=e["delay_days"], vendor=po["vendor"], cause=e["cause"])

    def _apply_mitigation(self, project, e):
        """PM-approved vendor switch -> PO moves, and Engine 1 re-verifies the substitute against current policy."""
        if e["option"]["action"].startswith("Switch"):
            rep = self.store.get(project, e["option"]["evidence"])
            self.store.update(project, e["po"], vendor=rep["vendor"], status="issued", issued=e["today"],
                              committed_weeks=rep["lead_weeks"], value=rep["price"] or 0)
            self.verify_bid(project, rep["bid"], rep["tender"], as_of=e["today"])

    # ------------------------------------------------------------ human decisions
    def realize_delay(self, project, po, delay_days, cause):
        self.emit(project, "risk.realized", {"po": po, "delay_days": delay_days, "cause": cause})

    def approve_mitigation(self, project, pm, po, option, today):
        self.store.audit(project, pm, "mitigation.approved", {"po": po, "option": option})
        self.emit(project, "mitigation.approved", {"po": po, "option": option, "today": today, "pm": pm})

    def similar_risks(self, project, text, k=3):
        return [(s, pid, m["cause"], m["delay_days"]) for s, pid, m, _ in
                self.index.search(text, k=k, kind="risk_precedent", client=commissioning.client_of(self.store, project))]

    # ------------------------------------------------------------ dashboards (Phase 4) + access (Phase 5)
    def check(self, user, project, role=None):
        if self.access is None:
            return
        a = self.access.get(user)
        if not a or (a["projects"] != "*" and project not in a["projects"]) or (role and role not in a["roles"]):
            self.store.audit(project, user, "access.denied", {"role": role})
            raise PermissionError(f"{user} may not view {project} as {role}")

    def dashboard(self, user, project, role):
        self.check(user, project, role)
        s = self.store
        if role == "pm":
            risks = sorted((r for r in s.find(project, "risk") if r["status"] == "open"),
                           key=lambda r: (-r["slip_days"], -r["score"]))
            return {"project_slip_days": max((r["slip_days"] for r in risks), default=0),
                    "top_risks": [{"activity": r["activity"], "slip": r["slip_days"], "score": r["score"],
                                   "sources": r["sources"], "driven_by": r["driven_by"],
                                   "do": (r["top_mitigation"] or {}).get("action") or
                                   (r["driven_by"] and f"recover {r['driven_by']} first")}
                                  for r in risks[:5]]}
        if role == "procurement":
            return {"vendors": [{"vendor": r["vendor"], "compliance": r["compliance_ratio"],
                                 "fulfilment": verification.fulfilment_score(s, project, r["vendor"], r["category"],
                                                                             r["lead_weeks"])["score"],
                                 "vendor_risk": r["vendor_risk"], "deviations": r["counts"]["deviation"]}
                                for r in s.find(project, "verification_report")],
                    "watch_pos": [po["id"] for po in s.find(project, "po") if po.get("watch")]}
        if role == "quality":
            q = verification.review_queue(s, project)
            cases = s.find(project, "test_case")
            return {"review_queue": {sev: sum(f["severity"] == sev for f in q) for sev in ("high", "medium", "low")},
                    "commissioning": {"passed": sum(c["status"] == "passed" for c in cases), "total": len(cases),
                                      "on_hold": sum(bool(c.get("hold")) for c in cases)},
                    "open_ncrs": [n["id"] for n in s.find(project, "ncr") if n["status"] == "open"]}
        raise ValueError(role)

    def kpis(self, project):
        """Plan §9 leading indicators."""
        f = self.store.find(project, "finding")
        reviewed = [x for x in f if x["review"] not in ("pending", "n/a")]
        cases = self.store.find(project, "test_case")
        return {"bid_clauses_auto_cleared_pct": _pct(sum(x["auto_cleared"] for x in f), len(f)),
                "engineer_override_rate_pct": _pct(sum(x["review"] == "override" for x in reviewed), len(reviewed)),
                "test_cases_automated_pct": _pct(sum(c["mode"] == "auto" for c in cases), len(cases)),
                "ncr_recurrence": _recurrence(self.store.find(project, "ncr"))}

    def portfolio(self, user):
        """Phase 5: multi-project rollup, only over projects the user is entitled to."""
        projects = [p for p in self.store.projects() if self._allowed(user, p)]
        rows = []
        for p in projects:
            risks = [r for r in self.store.find(p, "risk") if r["status"] == "open"]
            rows.append({"project": p, "slip_days": max((r["slip_days"] for r in risks), default=0),
                         "open_ncrs": sum(n["status"] == "open" for n in self.store.find(p, "ncr")),
                         **self.kpis(p)})
        return sorted(rows, key=lambda r: -r["slip_days"])

    def _allowed(self, user, project):
        try:
            self.check(user, project)
            return True
        except PermissionError:
            return False


def suggest_threshold(store, project, current=verification.AUTO_CLEAR_MIN_CONFIDENCE, min_samples=20):
    """Phase 5: loosen auto-clear only when reviewers agreed with every rule-compliant verdict they saw."""
    # rule said compliant but confidence was below threshold -> a human looked: did they agree?
    seen = [f for f in store.find(project, "finding") if f["method"] == "rule" and f["status"] == "compliant"
            and not f["auto_cleared"] and f["review"] in ("accept", "reject_bid_item")]
    if len(seen) < min_samples or any(f["review"] == "reject_bid_item" for f in seen):
        return current
    return round(max(0.1, min(f["confidence"] for f in seen)), 3)


def _late_pos(summary):
    out = {}
    for r in summary["activities"]:
        for s in r["signals"]:
            if s.get("po") and s["delay_days"] > 0 and s["source"] in ("procurement", "logistics"):
                out[s["po"]] = f"+{s['delay_days']}d"
    return out


def _pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def _recurrence(ncrs):
    cats = [n["category"] for n in ncrs]
    return sum(cats.count(c) - 1 for c in set(cats))
