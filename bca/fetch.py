"""Download regulations and turn them into the local format.

A stored law looks like:
    {"id", "name", "source_url", "amended": "YYYYMMDD", "fetched": "YYYY-MM-DD",
     "articles": [{"article": "第 38 條", "chapter": "...", "section": "...", "text": "..."}]}
"""
import datetime
import html
import io
import json
import os
import re
import ssl
import time
import urllib.request
import zipfile

from . import config

UA = {"User-Agent": "Mozilla/5.0 (building-code-assistant)"}
MOJ_API = {"law": "https://law.moj.gov.tw/api/Ch/Law/JSON", "order": "https://law.moj.gov.tw/api/Ch/Order/JSON"}
MOJ_JSON = {"law": "ChLaw.json", "order": "ChOrder.json"}
CACHE_HOURS = 20


def _ssl_context():
    # Python 3.13+ rejects some government certificates that lack a Subject Key Identifier.
    # Keep full certificate verification, only drop that one strictness flag.
    ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _get(url, timeout=180):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        return r.read()


def _moj_dataset(kind):
    """The MOJ bulk file for laws or orders; reused for a day so one update is a single download."""
    cache = os.path.join(config.home(), "cache")
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, MOJ_JSON[kind])
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_HOURS * 3600:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    raw = _get(MOJ_API[kind])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        data = json.loads(z.read(MOJ_JSON[kind]).decode("utf-8-sig"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def parse_moj_law(raw, entry):
    """Convert one MOJ law record. Chapter/section headings (type C) become labels on the articles."""
    chapter = section = ""
    articles = []
    for a in raw["LawArticles"]:
        text = a["ArticleContent"].replace("\r\n", "\n").strip()
        if a["ArticleType"] == "C":
            if "節" in text and "章" not in text:
                section = text
            else:
                chapter, section = text, ""
            continue
        articles.append({"article": a["ArticleNo"].strip(), "chapter": chapter, "section": section, "text": text})
    return {
        "id": entry["id"],
        "name": entry["name"],
        "source_url": raw["LawURL"],
        "amended": raw["LawModifiedDate"],
        "fetched": datetime.date.today().isoformat(),
        "articles": articles,
    }


def fetch_moj(entries):
    """Fetch the given national entries. Returns (laws, errors)."""
    laws, errors = [], []
    datasets = {}
    for e in entries:
        kind = e["kind"]
        if kind not in datasets:
            datasets[kind] = {r["LawURL"].rsplit("pcode=", 1)[-1]: r for r in _moj_dataset(kind)["Laws"]}
        raw = datasets[kind].get(e["id"])
        if raw is None:
            errors.append(f"{e['name']}（{e['id']}）在全國法規資料庫找不到")
        elif raw.get("LawAbandonNote"):
            errors.append(f"{e['name']} 已廢止，略過")
        else:
            laws.append(parse_moj_law(raw, e))
    return laws, errors


def roc_to_ymd(text):
    """'民國 114 年 05 月 07 日' -> '20250507'."""
    m = re.search(r"民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", text)
    if not m:
        raise ValueError(f"cannot read date from: {text[:40]!r}")
    y, mo, d = (int(x) for x in m.groups())
    return f"{y + 1911:04d}{mo:02d}{d:02d}"


def parse_miaoli(page, entry):
    amended = roc_to_ymd(re.search(r"修正日期：</th>\s*<td>(.*?)</td>", page, re.S).group(1))
    block = re.search(r'<div id="[^"]*divLawContent\d*" class="ClearCss">(.*?)</div>', page, re.S).group(1)
    text = html.unescape(re.sub(r"<br\s*/?>", "\n", block.replace("\n", "")))
    text = re.sub(r"</?p[^>]*>|<[^>]+>", "", text).replace("\xa0", " ")
    parts = re.split(r"^\s*(第\s*\d+(?:-\d+)?\s*條)\s*$", text, flags=re.M)
    # parts = [preamble, no1, body1, no2, body2, ...]
    articles = []
    for i in range(1, len(parts) - 1, 2):
        body = "\n".join(l.rstrip() for l in parts[i + 1].strip().splitlines())
        articles.append({"article": re.sub(r"\s+", " ", parts[i]).strip(), "chapter": "", "section": "", "text": body})
    if not articles:
        raise ValueError("no articles found; the page layout may have changed")
    return {
        "id": entry["id"],
        "name": entry["name"],
        "source_url": entry["url"],
        "amended": amended,
        "fetched": datetime.date.today().isoformat(),
        "articles": articles,
    }


def fetch_local(entries):
    laws, errors = [], []
    for e in entries:
        try:
            page = _get(e["url"], timeout=60).decode("utf-8", errors="ignore")
            laws.append(parse_miaoli(page, e))
        except Exception as ex:  # one broken county page should not stop the update
            errors.append(f"{e['name']}：{ex}")
    return laws, errors
