"""The question-answering pipeline.

question -> (Haiku) rewrite into regulation wording -> BM25 over all loaded laws
         -> (Sonnet) answer using ONLY those articles, citing law + article.
"""
from . import config, llm, registry, store
from .search import Index, bigrams, excerpt

# Everyday words -> the words the regulations print. Added to every search, no model needed.
GLOSSARY = {
    "走道": "走廊", "廁所": "浴廁", "地下室": "地下層", "停車位": "停車空間", "頂樓加蓋": "屋頂突出物",
    "樓梯間": "樓梯", "電梯": "昇降機", "窗戶": "開口 窗", "裝潢": "室內裝修", "違建": "違章建築",
    "陽台": "陽臺", "改成": "變更使用 使用類組 變更使用執照", "改為": "變更使用 使用類組 變更使用執照",
    "隔間": "分間牆", "隔間牆": "分間牆", "打掉": "拆除", "雨遮": "雨遮 雨庇", "容積": "容積率", "蓋房子": "建造 建築許可",
}

REWRITE_PROMPT = """你在協助搜尋台灣的建築相關法規（建築法、建築技術規則、室內裝修管理辦法、各縣市建築自治條例等）。
使用者的問題是口語，但法規條文用的是正式用語。
請把問題改寫成**最多 6 個**搜尋詞：
- 優先寫法規條文裡實際會出現的寫法（例如：地下室→地下層、停車位→停車空間、頂樓加蓋→屋頂突出物）
- 如果問題涉及某種建築用途，寫出它在法規裡可能歸屬的類別名稱
- 如果問題在問「要不要申請／許可」，加上「申請 許可」與可能相關的法規名稱關鍵字
- 只寫跟問題直接相關的詞，不要加泛用詞
- 只輸出搜尋詞，用空格分隔，不要回答問題、不要解釋

問題：{question}"""

SYSTEM = """你是台灣建築法規助理，只能根據使用者提供的條文回答。
目前載入的法規（括號內是修正日期）：
{laws}
使用者所在地區：{region}

規則：
1. 只用提供的條文內容回答，不要用記憶補充數字或條件。
2. 每個結論後面標註出處，格式如（建築技術規則建築設計施工編 第 38 條第 1 項）。
3. 若問題還取決於上面清單以外的法規（例如其他縣市自治條例、都市計畫書的土地使用分區管制、
   消防以外的專業法規），明確說「這點需要查閱 ○○，目前沒有載入」，不要猜。
4. 提供的條文找不到答案時，直接說找不到，不要硬湊。
5. 不同層級的規定都要列出：全國法規（建築法、建築技術規則）和地方自治條例可能同時適用，
   地方規定有時比全國更嚴格，兩者衝突時要提醒使用者向主管機關確認。
6. 回答前先看該法規的適用範圍條文（通常是第 1–3 條）：某行為被列入定義，不代表所有建築物都必須辦理；
   適用範圍有但書、而使用者的情況無法從條文判斷時，要明說，不要用「很可能需要」之類的傾向性說法代替。
7. 用繁體中文，簡短條列，先給結論再給條件／例外。你不是主管機關，最後不必重複免責聲明。"""


class Assistant:
    def __init__(self):
        self.cfg = config.load()
        entries = registry.all_entries(self.cfg.get("region"))
        self.laws = store.load_all(entries, self.cfg.get("pins"))
        if not self.laws:
            raise RuntimeError("還沒有任何法規資料。請先執行：bca setup（或 bca update）")
        self.index = Index(self.laws)
        self.backend = self.cfg.get("backend", "auto")

    def _system(self):
        laws = "\n".join(f"- {l['name']}（{l['amended']}）" for l in self.laws)
        return SYSTEM.format(laws=laws, region=self.cfg.get("region") or "未指定（只有全國法規）")

    def retrieve(self, question, k_plain=12, k_rewritten=8):
        terms = llm.complete(REWRITE_PROMPT.format(question=question), "fast", backend=self.backend)
        terms = terms.splitlines()[-1].strip()
        extra = " ".join(v for k, v in GLOSSARY.items() if k in question)
        # Three searches, merged: the plain question, the model's rewritten terms, and the glossary
        # terms alone, so no single weak signal can push out what another one found.
        plain = self.index.search(f"{question} {extra}", k_plain)
        rewritten = self.index.search(f"{terms} {extra}", k_rewritten)
        glossary = self.index.search(extra, 5) if extra else []  # the glossary terms alone
        picked = list(dict.fromkeys(plain + rewritten + glossary))
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
