"""The question-answering pipeline.

question -> (Haiku) rewrite into regulation wording -> BM25 over all loaded laws
         -> (Sonnet) answer using ONLY those articles, citing law + article.
"""
import json
import os

from . import config, llm, registry, store
from .search import Index, bigrams, excerpt

# Everyday words -> the words the regulations print. Added to every search, no model needed.
# Prompts and the glossary live in prompts.json so the web page uses exactly the same text.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json"), encoding="utf-8") as _f:
    _P = json.load(_f)
GLOSSARY = _P["glossary"]  # everyday word -> the word the regulations print; added to every search
REWRITE_PROMPT = _P["rewrite_prompt"]
SYSTEM = _P["system"]


class Assistant:
    def __init__(self, region=None):
        """region overrides the configured one (used by the eval, which covers several regions)."""
        self.cfg = config.load()
        if region:
            self.cfg["region"] = region
        entries = registry.all_entries(self.cfg.get("region"))
        self.laws = store.load_all(entries, self.cfg.get("pins"))
        if not self.laws:
            raise RuntimeError("還沒有任何法規資料。請先執行：bca setup（或 bca update）")
        self.index = Index(self.laws)
        # The region's ordinances also get an index of their own. Word weights are then computed
        # among local articles only, so a few hundred of them are not drowned by national law.
        local_ids = {e["id"] for e in registry.local_for(self.cfg.get("region"))}
        self.local_index = Index([l for l in self.laws if l["id"] in local_ids])
        self.doc_position = {(d["law_id"], d["article"]): i for i, d in enumerate(self.index.docs)}
        self.backend = self.cfg.get("backend", "auto")

    def _system(self):
        laws = "\n".join(f"- {l['name']}（{l['amended']}）" for l in self.laws)
        return SYSTEM.format(laws=laws, region=self.cfg.get("region") or "未指定（只有全國法規）")

    def retrieve(self, question, k_plain=12, k_rewritten=8):
        terms = llm.complete(REWRITE_PROMPT.format(question=question), "fast", backend=self.backend)
        terms = terms.splitlines()[-1].strip()
        extra = " ".join(v for k, v in GLOSSARY.items() if k in question)
        # Several searches, merged: the plain question, the model's rewritten terms, the glossary
        # terms alone, and the local ordinances alone. No single weak signal can push out what
        # another one found, and a few hundred local articles are not drowned by national law.
        plain = self.index.search(f"{question} {extra}", k_plain)
        rewritten = self.index.search(f"{terms} {extra}", k_rewritten)
        glossary = self.index.search(extra, 5) if extra else []  # the glossary terms alone
        local = [self.doc_position[(d["law_id"], d["article"])]
                 for d in (self.local_index.docs[i] for i in self.local_index.search(f"{question} {extra}", 8))]
        picked = list(dict.fromkeys(plain + rewritten + glossary + local))
        picked += self._scope_articles(picked)
        return terms, [self.index.docs[i] for i in picked]

    def _scope_articles(self, picked, min_hits=3, first_n=3, max_len=300):
        """For a law with several hits, add its opening short articles: they usually say who the law applies to."""
        per_law = {}
        for i in picked:
            per_law[self.index.docs[i]["law_id"]] = per_law.get(self.index.docs[i]["law_id"], 0) + 1
        have, extra = set(picked), []
        for law_id, n in per_law.items():
            if n < min_hits:
                continue
            opening = [i for i, d in enumerate(self.index.docs) if d["law_id"] == law_id][:first_n]
            extra += [i for i in opening if i not in have and len(self.index.docs[i]["text"]) <= max_len]
        return extra

    def ask(self, question):
        terms, hits = self.retrieve(question)
        parts = []
        for d in hits:
            where = d["chapter"].strip() + (" " + d["section"].strip() if d["section"] else "")
            parts.append(f"【{d['law']} {d['article']}】（{where.strip() or '—'}）\n{excerpt(d['text'], question)}")
        prompt = "條文：\n" + "\n\n".join(parts) + f"\n\n問題：{question}"
        answer = llm.complete(prompt, "smart", system=self._system(), backend=self.backend)
        return {"terms": terms, "hits": hits, "answer": answer}

    def footer(self, result):
        """Versions of the laws that were consulted, so the user can tell how current the answer is."""
        used = {}
        for d in result["hits"]:
            if d["law"] in result["answer"]:  # only laws the answer actually cites
                used[d["law"]] = d["amended"]
        lines = [f"  {name}（{date}）" for name, date in used.items()]
        return "參考的法規版本：\n" + "\n".join(lines) + "\n※ 僅供參考，實際以主管建築機關解釋為準。"
