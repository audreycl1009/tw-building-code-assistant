"""Keyword search (BM25 over character bigrams) across every loaded law.

Chinese has no spaces, so text is cut into overlapping 2-character pieces. No model, no cost.
"""
import math
from collections import Counter, defaultdict

# Variant characters people type vs. what the regulation prints (臺/台, 欄桿/欄杆 ...).
NORMALIZE = str.maketrans({"臺": "台", "桿": "杆", "廁": "厕", "裡": "里", "裏": "里", "線": "线", "衞": "卫", "衛": "卫"})


def bigrams(text):
    chars = [c for c in text.translate(NORMALIZE) if not c.isspace()]
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


class Index:
    def __init__(self, laws):
        self.docs = []  # one dict per article, with the law it belongs to
        for law in laws:
            for a in law["articles"]:
                self.docs.append({**a, "law_id": law["id"], "law": law["name"], "amended": law["amended"]})
        counts = [Counter(bigrams(d["chapter"] + d["section"] + d["text"])) for d in self.docs]
        self.doc_len = [sum(c.values()) for c in counts]
        self.avg_len = (sum(self.doc_len) / len(self.docs)) if self.docs else 1.0
        self.postings = defaultdict(list)  # bigram -> [(doc index, count)]
        for i, c in enumerate(counts):
            for bg, n in c.items():
                self.postings[bg].append((i, n))

    def search(self, query, k=10, k1=1.5, b=0.75):
        """Top-k doc indices, best first."""
        n = len(self.docs)
        scores = defaultdict(float)
        for bg in set(bigrams(query)):
            plist = self.postings.get(bg)
            if not plist:
                continue
            idf = math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for i, tf in plist:
                scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.doc_len[i] / self.avg_len))
        return sorted(scores, key=lambda i: -scores[i])[:k]

    def rank_of(self, query, law_id, article):
        """1-based rank of an article for a query (None if it never matches). For evaluation."""
        ranking = self.search(query, k=len(self.docs))
        for pos, i in enumerate(ranking, 1):
            if self.docs[i]["law_id"] == law_id and self.docs[i]["article"] == article:
                return pos
        return None


def excerpt(text, query, limit=3000):
    """Keep long articles readable: header line plus the lines that best match the query, in order."""
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    q = set(bigrams(query))
    scored = sorted(range(1, len(lines)), key=lambda i: -len(q & set(bigrams(lines[i]))))
    keep, used = {0}, len(lines[0])
    for i in scored:
        if used + len(lines[i]) > limit:
            continue
        keep.add(i)
        used += len(lines[i])
    out = [lines[i] for i in sorted(keep)]
    if len(keep) < len(lines):
        out.append("（本條較長，以上為與問題最相關的款項，其餘省略）")
    return "\n".join(out)
