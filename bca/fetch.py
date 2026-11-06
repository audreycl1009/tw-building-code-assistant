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


ZH_DIGITS = {"零": 0, "○": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
ZH_NUM = "一二三四五六七八九十百千零○〇"


def zh_to_int(text):
    """'一百零一' -> 101, '二十' -> 20, '12' -> 12."""
    if text.isdigit():
        return int(text)
    total, digit = 0, 0
    for ch in text:
        if ch in ZH_DIGITS:
            digit = ZH_DIGITS[ch]
        else:
            total += (digit or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            digit = 0
    return total + digit


ARTICLE_HEAD = re.compile(rf"^第\s*(\d+|[{ZH_NUM}]+)\s*(?:-\s*(\d+)\s*)?條(?:\s*之\s*([{ZH_NUM}\d]+))?(?=\s|$)(.*)$")
PART_HEAD = re.compile(rf"^第\s*(?:\d+|[{ZH_NUM}]+)\s*(編|章|節)(?:\s|$)")
LIST_MARK = re.compile(rf"^(?:[{ZH_NUM}]+[、．.\s]|[（(][{ZH_NUM}\d]+[）)]|\d+[、．.]|[甲乙丙丁戊己庚辛壬癸][、．])")
TABLE_CHARS = re.compile(r"[┌┬┐├┼┤└┴┘│┃─━]")
COLUMN_GAP = re.compile(r"\S[ 　\xa0]{2,}\S")
INNER_TABLE = re.compile(r"<table\b(?:(?!<table\b).)*?</table>", re.S | re.I)  # innermost tables only
MAX_ARTICLE_GAP = 5  # deleted articles leave small gaps; a bigger jump is an in-text reference


def _tabular(line):
    return " | " in line or bool(TABLE_CHARS.search(line) or COLUMN_GAP.search(line[6:]))


def unwrap(text):
    """County sites hard-wrap lines at a fixed width. Rejoin them so each line is a whole sentence or item.

    A line ending in sentence punctuation stays a line, which keeps 項 and 款 apart; tables are left alone.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip(" \t　\xa0")
        if not line:
            continue
        joinable = out and not out[-1].endswith(("。", "；", "：", "？", "！"))
        if joinable and not LIST_MARK.match(line) and not _tabular(out[-1]) and not _tabular(line):
            out[-1] += line
        else:
            out.append(line)
    return "\n".join(out)


def _balanced(page, start, tag):
    """The HTML from `start` to the end tag that closes it, counting nested tags of the same name."""
    depth, pos = 0, start
    pattern = re.compile(rf"<(/?){tag}\b[^>]*>", re.I)
    for m in pattern.finditer(page, pos):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return page[start:m.end()]
    raise ValueError(f"unclosed <{tag}>")


def _cell_text(cell):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()


def _table_rows(match):
    """An HTML table inside an article -> one 'cell | cell | cell' line per row."""
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", match.group(0), re.S | re.I):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        rows.append(" | ".join(_cell_text(c) for c in cells))
    return "\n" + "\n".join(rows) + "\n"


def _flatten(fragment, keep_newlines=False):
    """HTML -> plain text. Tables inside an article become ' | ' rows; other markup is dropped."""
    if not keep_newlines:
        fragment = fragment.replace("\r", "").replace("\n", "")
    fragment = INNER_TABLE.sub(_table_rows, fragment)
    fragment = re.sub(r"<br\s*/?>|</p>|</tr>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</t[dh]>", "\u3000\u3000", fragment, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ")


def split_articles(text):
    """Plain law text -> article dicts. Article numbers must increase, so a line that merely starts
    with a reference such as '第三十六條 規定' is not mistaken for a new article."""
    articles, chapter, section, body = [], "", "", []
    last = None

    def flush():
        if articles and body:  # a chapter heading flushes too; a second flush must not blank the article
            articles[-1]["text"] = unwrap("\n".join(body))
        body.clear()

    for raw in text.splitlines():
        line = raw.strip(" \t　\xa0")
        if " | " in line:  # a table row, even if its first cell looks like a heading
            if articles:
                body.append(raw)
            continue
        head = ARTICLE_HEAD.match(line)
        if head:
            main = zh_to_int(head.group(1))
            sub = head.group(2) or head.group(3)
            key = (main, zh_to_int(sub) if sub else 0)
            if last is None or (key > last and main - last[0] <= MAX_ARTICLE_GAP):
                flush()
                last = key
                number = f"{key[0]}-{key[1]}" if key[1] else str(key[0])
                articles.append({"article": f"第 {number} 條", "chapter": chapter, "section": section, "text": ""})
                body.append(head.group(4))
                continue
        part = PART_HEAD.match(line)
        if part and len(line) < 40 and "。" not in line:
            flush()
            if part.group(1) == "節":
                section = line
            else:
                chapter, section = line, ""
            continue
        if articles:
            body.append(raw)
    flush()
    return articles


def _law(entry, amended, articles):
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


def parse_glrs(page, entry):
    """The 主管法規共用系統 several counties use (苗栗、臺南、臺中). Text sits in a div or in a table."""
    date = re.search(r"修正日期：</th>\s*<td>(.*?)</td>", page, re.S) or re.search(r"公發布日：</th>\s*<td>(.*?)</td>", page, re.S)
    block = re.search(r'<table id="[^"]*tableLawArticle[^"]*"', page)
    tag = "table"
    if not block:
        block, tag = re.search(r'<div id="[^"]*divLawContent\d*"', page), "div"
    if not date or not block:
        raise ValueError("page layout not recognised")
    content = _balanced(page, block.start(), tag)
    content = content[content.index(">") + 1:content.rindex("<")]  # drop the outer tag: it is layout, not a law table
    return _law(entry, roc_to_ymd(date.group(1)), split_articles(_flatten(content)))


TAIPEI_ITEM = re.compile(
    r'<li class="chapter-\d+">(?P<part>.*?)</li>'
    r'|<div class="col-no">(?P<no>.*?)</div>\s*<div class="col-data">\s*<div class="law-articlepre">(?P<text>.*?)</div>\s*</div>',
    re.S,
)


def parse_taipei(page, entry):
    """臺北市法規查詢系統 (laws.gov.taipei): one list item per article, text in a preformatted block."""
    date = re.search(r"(?:修正|發布|公布)日期</label>.*?<dfn>(.*?)</dfn>", page, re.S)
    if not date:
        raise ValueError("page layout not recognised")
    chapter = section = ""
    articles = []
    for m in TAIPEI_ITEM.finditer(page):
        if m.group("part") is not None:
            title = html.unescape(re.sub(r"<[^>]+>", "", m.group("part"))).strip()
            if "節" in title and "章" not in title:
                section = title
            else:
                chapter, section = title, ""
            continue
        number = re.sub(r"\s+", " ", html.unescape(m.group("no"))).strip()
        text = unwrap(_flatten(m.group("text"), keep_newlines=True))
        articles.append({"article": number, "chapter": chapter, "section": section, "text": text})
    return _law(entry, roc_to_ymd(html.unescape(date.group(1))), articles)


PARSERS = {"glrs": parse_glrs, "taipei": parse_taipei}


def fetch_local(entries):
    laws, errors = [], []
    for e in entries:
        try:
            page = _get(e["url"], timeout=60).decode("utf-8", errors="ignore")
            laws.append(PARSERS[e["source"]](page, e))
        except Exception as ex:  # one broken county page should not stop the update
            errors.append(f"{e['name']}：{ex}")
    return laws, errors
