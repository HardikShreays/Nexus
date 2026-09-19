"""Phase 0 — vector index for clause / test / failure-precedent retrieval.

ponytail: pure-Python TF-IDF cosine. Fine for thousands of clauses per project; swap `_vec`
for Bedrock embeddings + OpenSearch k-NN / pgvector once corpora reach 100k+ chunks.
"""
import math
import re
from collections import Counter

STOP = set("a an and are as at be by for from in is it of on or shall the to with be all per must should".split())


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class Index:
    def __init__(self):
        self.docs = {}  # id -> (Counter, meta, text)
        self.df = Counter()

    def add(self, id, text, **meta):
        if id in self.docs:
            self.df.subtract(set(self.docs[id][0]))
        tf = Counter(tokens(text))
        self.docs[id] = (tf, meta, text)
        self.df.update(set(tf))

    def _vec(self, tf):
        n = len(self.docs) or 1
        v = {t: c * math.log(1 + n / (1 + self.df[t])) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def search(self, query, k=5, **where):
        """Return [(score, id, meta, text)]. `where` filters meta exactly — always pass project."""
        q = self._vec(Counter(tokens(query)))
        hits = []
        for id, (tf, meta, text) in self.docs.items():
            if any(meta.get(key) != val for key, val in where.items()):
                continue
            d = self._vec(tf)
            s = sum(w * d.get(t, 0.0) for t, w in q.items())
            if s > 0:
                hits.append((round(s, 4), id, meta, text))
        return sorted(hits, key=lambda h: -h[0])[:k]
