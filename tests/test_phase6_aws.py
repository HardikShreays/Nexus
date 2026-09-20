"""Phase 6 — AWS bindings. Inert without env vars (so every other test runs offline), and
wired into the real write paths when the env vars are set."""
import json

import pytest

import serve
from conftest import ROOT
from epc import aws
from epc.platform import Platform

P = "MUM-DC1"


@pytest.fixture
def calls(monkeypatch):
    """Capture boto3 calls instead of making them."""
    seen = []

    class Fake:
        def __init__(self, service):
            self.service = service

        def __getattr__(self, op):
            return lambda **kw: seen.append((self.service, op, kw)) or {
                "Blocks": [{"BlockType": "LINE", "Text": "[X-01] Output voltage 415 V"}],
                "Body": type("B", (), {"read": lambda s: b"[X-01] Output voltage 415 V"})(),
            }

    aws._client.cache_clear()
    monkeypatch.setattr(aws, "_client", Fake)
    return seen


def test_inert_without_env(monkeypatch, calls):
    """No AWS call happens unless the binding's variable is set — this is what keeps the
    other suites offline."""
    for var in ("EPC_S3_BUCKET", "EPC_AUDIT_TABLE", "EPC_EVENT_BUS"):
        monkeypatch.delenv(var, raising=False)
    plat = Platform()
    plat.store.put(P, "project", P, {"name": "t"})
    plat.emit(P, "bid.verified", {"bid": "BID-AMPCORE"})
    assert calls == []
    assert aws.read_doc(ROOT / "sample_data" / "tender.md").startswith("#")


def test_audit_rows_mirror_to_dynamodb(monkeypatch, calls):
    monkeypatch.setenv("EPC_AUDIT_TABLE", "epc-nexus-audit")
    monkeypatch.delenv("EPC_EVENT_BUS", raising=False)
    plat = Platform()
    plat.store.audit(P, "qe.rao", "finding.reviewed", {"finding": "F-1"})
    (service, op, kw), = calls
    assert (service, op) == ("dynamodb", "put_item")
    assert kw["Item"]["project"]["S"] == P and kw["Item"]["seq"]["N"] == "1"
    assert "attribute_not_exists" in kw["ConditionExpression"]  # append-only


def test_events_publish_to_eventbridge(monkeypatch, calls):
    monkeypatch.setenv("EPC_EVENT_BUS", "epc-nexus-bus")
    monkeypatch.delenv("EPC_AUDIT_TABLE", raising=False)
    plat = Platform()
    plat.emit(P, "bid.verified", {"bid": "BID-AMPCORE", "risk": 0.4})
    (service, op, kw), = calls
    assert (service, op) == ("events", "put_events")
    entry, = kw["Entries"]
    assert entry["DetailType"] == "bid.verified"
    assert json.loads(entry["Detail"]) == {"project": P, "bid": "BID-AMPCORE", "risk": 0.4}


@pytest.mark.parametrize("name,service", [("tender.md", "s3"), ("tender.pdf", "textract")])
def test_documents_load_from_s3_scans_via_textract(monkeypatch, calls, name, service):
    monkeypatch.setenv("EPC_S3_BUCKET", "epc-nexus-docs")
    text = aws.read_doc(ROOT / "sample_data" / name)
    assert calls[0][0] == service
    assert "415 V" in text  # both paths hand epc.ingest the same line-per-clause shape


def test_lambda_handler_serves_page_and_state():
    assert serve.handler({"rawPath": "/"}, None)["statusCode"] == 200
    body = json.loads(serve.handler({"rawPath": "/api/state"}, None)["body"])
    assert body["audit"]["valid"] and body["engine1"] and body["kpis"]
