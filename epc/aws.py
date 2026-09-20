"""AWS bindings for the swap-in points the local implementation stands in for.

Every helper is inert unless its environment variable is set, so `python3 demo.py` and the
test suite still run offline with zero AWS calls and zero credentials.

    EPC_S3_BUCKET    documents read from S3 (scans/PDFs via Textract) instead of sample_data/
    EPC_AUDIT_TABLE  every audit row mirrored to DynamoDB, append-only by condition
    EPC_EVENT_BUS    every engine event published to EventBridge
    EPC_LLM=1        clause reasoning on Bedrock (see epc/llm.py)

ponytail: one module, boto3 imported lazily, no abstraction over the SDK — each binding is a
handful of lines against shapes the local code already produces. Calls are not swallowed: if
AWS rejects a write the engine should fail loudly, not silently drop an audit row.
"""
import functools
import json
import os

SCANNED = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")


@functools.lru_cache(maxsize=None)
def _client(service):
    import boto3  # only needed when a binding is switched on
    return boto3.client(service, region_name=os.environ.get("AWS_REGION", "us-east-1"))


def read_doc(path):
    """Document text for ingest(). S3 when EPC_S3_BUCKET is set, else the local file."""
    bucket = os.environ.get("EPC_S3_BUCKET")
    if not bucket:
        return path.read_text()
    key = f"{os.environ.get('EPC_S3_PREFIX', 'documents')}/{path.name}"
    if path.suffix.lower() in SCANNED:
        return textract_text(bucket, key)
    return _client("s3").get_object(Bucket=bucket, Key=key)["Body"].read().decode()


def textract_text(bucket, key):
    """Scanned tender/bid pages -> the line-per-clause text epc.ingest parses.

    ponytail: synchronous DetectDocumentText — images and single-page PDFs. Multi-page tender
    PDFs need StartDocumentTextDetection + the SNS/poll round trip; add it when the pilot's
    document inventory shows multi-page scans.
    """
    blocks = _client("textract").detect_document_text(
        Document={"S3Object": {"Bucket": bucket, "Name": key}})["Blocks"]
    return "\n".join(b["Text"] for b in blocks if b["BlockType"] == "LINE")


def put_audit(project, seq, ts, actor, action, payload, prev_hash, hash):
    """Mirror one hash-chained audit row into DynamoDB. The condition makes it append-only."""
    table = os.environ.get("EPC_AUDIT_TABLE")
    if not table:
        return
    _client("dynamodb").put_item(
        TableName=table,
        Item={"project": {"S": project}, "seq": {"N": str(seq)}, "ts": {"N": repr(ts)},
              "actor": {"S": actor}, "action": {"S": action}, "payload": {"S": payload},
              "prev_hash": {"S": prev_hash}, "hash": {"S": hash}},
        ConditionExpression="attribute_not_exists(#p) AND attribute_not_exists(#s)",
        ExpressionAttributeNames={"#p": "project", "#s": "seq"})


def put_event(project, event, payload):
    """Publish an engine event to EventBridge. Handlers stay in-process; the bus is the
    integration seam for Step Functions / Lambda targets outside this deployment."""
    bus = os.environ.get("EPC_EVENT_BUS")
    if not bus:
        return
    _client("events").put_events(Entries=[{
        "EventBusName": bus, "Source": "epc.platform", "DetailType": event,
        "Detail": json.dumps({"project": project, **payload}, default=str)}])
