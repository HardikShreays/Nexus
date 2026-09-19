"""Optional Claude-on-Bedrock reasoning for clauses the deterministic rules cannot judge.

Off unless EPC_LLM=1 (tests and demo stay offline). Requires `pip install anthropic` + AWS creds.
Engines never let the LLM clear an item on its own: its verdict is recorded with provenance and
the item still goes to the human review queue.
"""
import json
import os

MODEL = os.environ.get("EPC_MODEL", "anthropic.claude-opus-5")


def enabled():
    return os.environ.get("EPC_LLM") == "1"


def judge_clause(spec_text, bid_text):
    """-> {"verdict": compliant|deviation|unclear, "reason": str, "model": str} or None when disabled."""
    if not enabled():
        return None
    from anthropic import AnthropicBedrockMantle

    client = AnthropicBedrockMantle(aws_region=os.environ.get("AWS_REGION", "us-east-1"))
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content":
                   "You check EPC vendor bids against data-centre tender specifications.\n"
                   f"SPEC CLAUSE: {spec_text}\nBID CLAUSE: {bid_text or '(no matching bid clause)'}\n"
                   'Reply with JSON only: {"verdict": "compliant"|"deviation"|"unclear", "reason": "<one sentence>"}'}],
    )
    if msg.stop_reason == "refusal":
        return {"verdict": "unclear", "reason": "model refused", "model": MODEL}
    text = "".join(b.text for b in msg.content if b.type == "text")
    try:
        out = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except ValueError:
        out = {"verdict": "unclear", "reason": text[:200]}
    return {**out, "model": MODEL}
