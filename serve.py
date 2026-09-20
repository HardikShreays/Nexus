"""Web frontend. Local: python3 serve.py → http://localhost:8000. Deployed: `handler` behind
an AWS Lambda Function URL (see infra/deploy.sh).

ponytail: http.server locally, one Lambda + Function URL in AWS — no ALB, no API Gateway, no
container. The pipeline is the demo one, run once per process/cold start and held in memory;
same swap-in points as demo.py. Add a front door only when this needs auth or a custom domain.
"""
import http.server
import json
import pathlib

import demo
from epc import commissioning as cx
from epc import risk
from epc.platform import Platform

P = demo.P
HERE = pathlib.Path(__file__).parent
STATE = None


def state():
    """Built once per process. On Lambda that is once per cold start."""
    global STATE
    if STATE is None:
        STATE = build_state()
    return STATE


def build_state():
    """The whole demo run, as one JSON blob."""
    plat = Platform(*demo.load_pilot())
    data, tel = demo.load_schedule_data(), demo.load_telemetry()
    today = data["today"]

    reports = demo.run_engine1(plat.store, plat.index, today)
    for rep in reports:
        rep["deviations"] = [plat.store.get(P, fid) for fid in rep["ranked_deviations"]]

    risk.load_schedule(plat.store, P, data)
    forecast = plat.assess(P, data["feeds"], today)

    cases = cx.generate_cases(plat.store, P, "IST-UPS", tel["points"])
    plat.run_commissioning(P, tel["readings"])
    pkg = cx.package(plat.store, P)

    project = plat.store.get(P, P)
    return {
        "project": {**project, "id": P, "today": today},
        "engine1": reports,
        "engine2": forecast,
        "engine3": {"cases": cases, "ncrs": plat.store.find(P, "ncr"), "package": pkg,
                    "markdown": cx.package_markdown(pkg)},
        "dashboards": {role: plat.dashboard("web", P, role) for role in ("pm", "procurement", "quality")},
        "kpis": plat.kpis(P),
        "audit": {"valid": plat.store.verify_audit(), "log": plat.store.audit_log(P)},
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE / "web"), **kw)

    def do_GET(self):
        if self.path.split("?")[0] != "/api/state":
            return super().do_GET()
        body = json.dumps(state()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def handler(event, context):
    """AWS Lambda Function URL entry point (payload format 2.0)."""
    path = event.get("rawPath", "/").split("?")[0]
    if path == "/api/state":
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(state())}
    if path == "/app" or path == "/app.html":
        return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": (HERE / "web" / "app.html").read_text()}
    return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body": (HERE / "web" / "index.html").read_text()}


if __name__ == "__main__":
    print("running pipeline...")
    state()
    print("http://localhost:8000")
    http.server.HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
