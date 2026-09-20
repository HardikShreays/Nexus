"""Phase 0 — ingestion: equipment taxonomy, clause parsing, parameter extraction, unit normalisation.

Document text format (what Textract/Unstructured output gets normalised to):
    ## UPS                      <- heading = category hint for following clauses
    [PWR-UPS-01] Output voltage 415 V ±1%
    [PWR-UPS-02] Efficiency at 50% load >= 96 %
Lines without a [ID] get auto-numbered. Blank lines and other headings are ignored.


ponytail: .txt/.md only. PDFs/DWGs go through Textract before reaching here — add a loader
when the pilot's document inventory (Phase 0 discovery) says which formats actually exist.
"""
import hashlib
import re

# system -> category -> keywords. Owned by the domain SME; extend here, never in engine code.
TAXONOMY = {
    "power": {
        "ups": ["ups", "uninterruptible"],
        "generator": ["generator", "genset", "dg set", "diesel"],
        "switchgear": ["switchgear", "acb", "vcb", "breaker", "lt panel", "ht panel"],
        "transformer": ["transformer"],
        "grid": ["discom", "substation", "grid", "utility"],
    },
    "cooling": {
        "chiller": ["chiller"],
        "crah": ["crah", "crac", "air handler"],
        "cooling_tower": ["cooling tower"],
    },
    "it": {"rack": ["rack", "cabinet"], "pdu": ["pdu", "rpp"]},
    "fire": {"fire_suppression": ["fire", "suppression", "vesda", "novec"]},
}

# unit -> (dimension, factor to base unit)
UNITS = {
    "v": ("voltage", 1), "kv": ("voltage", 1e3),
    "a": ("current", 1), "ka": ("current", 1e3),
    "w": ("power", 1), "kw": ("power", 1e3), "mw": ("power", 1e6),
    "va": ("apparent", 1), "kva": ("apparent", 1e3), "mva": ("apparent", 1e6),
    "tr": ("cooling", 3.517e3),
    "ms": ("time", 1e-3), "s": ("time", 1), "sec": ("time", 1), "min": ("time", 60), "h": ("time", 3600),
    "hours": ("time", 3600), "days": ("duration", 1), "weeks": ("duration", 7),
    "hz": ("frequency", 1), "%": ("ratio", 1), "c": ("temperature", 1), "°c": ("temperature", 1),
    "db": ("sound", 1), "dba": ("sound", 1), "mm": ("length", 1e-3), "m": ("length", 1),
    "pa": ("pressure", 1), "kpa": ("pressure", 1e3), "bar": ("pressure", 1e5), "lps": ("flow", 1), "kg": ("mass", 1),
}

STANDARD_RE = re.compile(r"\b(IEC|IS|BIS|IEEE|TIA|EN|ISO|NFPA|ASHRAE|BICSI|CEA)[- ]?(\d+(?:[-.:]\d+)*)", re.I)
TIER_RE = re.compile(r"\b(tier\s*(?:iv|iii|ii|i|[1-4]))\b", re.I)
REDUND_RE = re.compile(r"\b(2n\s*\+\s*\d|2n|n\s*\+\s*\d|n(?=\s+(?:configuration|redundan)))(?![a-z0-9])", re.I)
UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
NUM_RE = re.compile(
    r"(?P<param>[a-z][a-z0-9 /()\-]*?)\s*(?P<op><=|>=|≤|≥|<|>|=|:)?\s*(?<![a-z0-9])(?P<val>-?\d+(?:\.\d+)?)\s*"
    rf"(?P<unit>{UNIT_ALT})?(?![a-z0-9])(?:\s*±\s*(?P<tol>\d+(?:\.\d+)?)\s*%)?", re.I)
QUALIFIERS = [("not exceed", "<="), ("not more than", "<="), ("maximum", "<="), ("max", "<="), ("within", "<="),
              ("less than", "<"), ("at least", ">="), ("not less than", ">="), ("minimum", ">="), ("min", ">=")]
LOAD_COND_RE = re.compile(r"\b(?:at|under|with)\s+(\d+)\s*%\s*load\b", re.I)  # "at 50% load" -> part of the param name
PARAM_STOP = {"the", "of", "at", "shall", "be", "with", "and", "a", "an", "is", "to", "for", "rated", "each", "load"}


def classify(text, hint=""):
    """(system, category) from heading hint first, then clause text."""
    for src in (hint, text):
        low = f" {src.lower()} "
        for system, cats in TAXONOMY.items():
            for cat, kws in cats.items():
                if any(re.search(rf"\b{re.escape(k)}\b", low) for k in kws):
                    return system, cat
    return "general", "general"


def param_key(words):
    return " ".join(w for w in re.findall(r"[a-z][a-z0-9]*", words.lower()) if w not in PARAM_STOP)


def extract_params(text, lenient=False):
    """Pull comparable requirements out of one clause.

    Returns [{"param", "op", "value", "unit", "dim", "base", "tol_pct"}]; text params (standards,
    redundancy, tier) have dim "text" and a string value. `lenient` (bids/datasheets) also keeps
    named unitless values ("power factor 0.99"); specs need an explicit comparator for those.
    """
    out = []
    for m in STANDARD_RE.finditer(text):
        out.append({"param": "standard", "op": "=", "value": f"{m.group(1).upper()} {m.group(2)}", "dim": "text"})
    for m in TIER_RE.finditer(text):
        tier = m.group(1).lower().replace(" ", "")
        tier = {"tier1": "tieri", "tier2": "tierii", "tier3": "tieriii", "tier4": "tieriv"}.get(tier, tier)
        out.append({"param": "tier", "op": "=", "value": tier, "dim": "text"})
    rest = TIER_RE.sub(" ", STANDARD_RE.sub(" ", text))
    
    for m in REDUND_RE.finditer(rest):
        out.append({"param": "redundancy", "op": "=", "value": m.group(1).upper().replace(" ", ""), "dim": "text"})
    rest = LOAD_COND_RE.sub(lambda m: f" load{m.group(1)}pct ", REDUND_RE.sub(" ", rest))
    
    for m in NUM_RE.finditer(rest):
        raw = m.group("param").strip().lower()
        op = {"≤": "<=", "≥": ">=", ":": "=", None: "="}.get(m.group("op"), m.group("op"))
        for q, qop in QUALIFIERS:
            if re.search(rf"\b{q}\b", raw):
                op = qop if op == "=" else op
                raw = re.sub(rf"\b{q}\b", " ", raw)
        key = param_key(raw.split(",")[-1])
        unit = (m.group("unit") or "").lower()
        # a bare number is only a requirement when an explicit comparator says so ("power factor >= 0.99")
        
        if not key or not (unit or lenient or m.group("op") in ("<=", ">=", "<", ">", "≤", "≥")):
            continue
        dim, factor = UNITS.get(unit, ("number", 1))
        val = float(m.group("val"))
        out.append({"param": key, "op": op, "value": val, "unit": unit, "dim": dim, "base": val * factor,
                    "tol_pct": float(m.group("tol")) if m.group("tol") else 0.0})
    return out


def parse_clauses(text, prefix, lenient=False):
    heading, n, out = "", 0, []
    
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            continue
        m = re.match(r"\[([^\]]+)\]\s*(.+)", line)
        n += 1
        cid, body = (m.group(1), m.group(2)) if m else (f"{prefix}-{n:03d}", line.lstrip("-* "))
        system, cat = classify(body, heading)
        out.append({"cid": cid, "text": body, "section": heading, "system": system, "category": cat,
                    "params": extract_params(body, lenient)})
    return out


def ingest(store, index, project, doc_id, text, doc_type, **meta):
    """Store raw doc + its clauses, link doc->clause in the graph, index every clause for RAG.

    doc_type: tender | bid | policy | procedure. Policies should carry version + effective date
    in `meta` so every compliance check can prove which version it ran against.
    """
    checksum = hashlib.sha256(text.encode()).hexdigest()
    store.put(project, "document", doc_id, {"doc_type": doc_type, "text": text, "sha256": checksum, **meta})
    clauses = []
    for c in parse_clauses(text, doc_id, lenient=doc_type == "bid"):
        cid = f"{doc_id}:{c['cid']}"
        clause = store.put(project, "clause", cid, {**c, "doc": doc_id, "doc_type": doc_type,
                                                     **{k: v for k, v in meta.items() if k in ("vendor", "version", "source")}})
        store.link(project, doc_id, "contains", cid)
        index.add(cid, f"{c['section']} {c['text']}", project=project, doc=doc_id, doc_type=doc_type,
                  category=c["category"])
        clauses.append(clause)
    store.audit(project, "ingest", "document.ingested", {"doc": doc_id, "type": doc_type, "sha256": checksum,
                                                          "clauses": len(clauses), **meta})
    return clauses
