"""Which regulations the assistant knows about.

National laws come from the 全國法規資料庫 open-data API (law.moj.gov.tw), keyed by `pcode`.
Local (county) ordinances come from each county's own law site, so each needs its own entry
and parser. 臺北市、臺中市、臺南市、苗栗縣 are included so far; see README "新增地區".
"""

# kind: "law" = 法律, "order" = 命令 (which MOJ file the law is in).
NATIONAL = [
    {"id": "D0070109", "name": "建築法", "kind": "law"},
    {"id": "D0070114", "name": "建築技術規則總則編", "kind": "order"},
    {"id": "D0070115", "name": "建築技術規則建築設計施工編", "kind": "order"},
    {"id": "D0070116", "name": "建築技術規則建築構造編", "kind": "order"},
    {"id": "D0070117", "name": "建築技術規則建築設備編", "kind": "order"},
    {"id": "D0070148", "name": "建築物室內裝修管理辦法", "kind": "order"},
    {"id": "D0070141", "name": "建築物使用類組及變更使用辦法", "kind": "order"},
    {"id": "D0070124", "name": "違章建築處理辦法", "kind": "order"},
    {"id": "D0070118", "name": "公寓大廈管理條例", "kind": "law"},
    {"id": "D0070119", "name": "公寓大廈管理條例施行細則", "kind": "order"},
    {"id": "D0070001", "name": "都市計畫法", "kind": "law"},
    {"id": "D0070012", "name": "都市計畫法臺灣省施行細則", "kind": "order"},
    {"id": "D0070028", "name": "都市計畫容積移轉實施辦法", "kind": "order"},
    {"id": "D0070113", "name": "建築基地法定空地分割辦法", "kind": "order"},
    {"id": "D0070131", "name": "山坡地建築管理辦法", "kind": "order"},
    {"id": "D0070147", "name": "建築物昇降設備設置及檢查管理辦法", "kind": "order"},
    {"id": "D0070149", "name": "建築物公共安全檢查簽證及申報辦法", "kind": "order"},
    {"id": "D0070150", "name": "原有合法建築物公共安全改善辦法", "kind": "order"},
    {"id": "D0120029", "name": "各類場所消防安全設備設置標準", "kind": "order"},
]

# Counties/cities. One with no entry in LOCAL has no ordinances collected yet;
# the assistant then answers from national law only and says so.
COUNTIES = [
    "基隆市", "臺北市", "新北市", "桃園市", "新竹市", "新竹縣", "苗栗縣", "臺中市",
    "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "臺南市", "高雄市", "屏東縣",
    "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣",
]

TAICHUNG = "https://law.taichung.gov.tw/LawContent.aspx?id="
TAINAN = "https://law01.tainan.gov.tw/glrsnewsout/LawContent.aspx?id="
TAIPEI = "https://laws.gov.taipei/law/LawSearch/LawArticleContent/"
MIAOLI = "https://law.miaoli.gov.tw/glrsnewsout/LawContent.aspx?id="


def _law(prefix, base, source, law_id, name):
    return {"id": f"{prefix}-{law_id}", "name": name, "source": source, "url": base + law_id}


LOCAL = {
    "臺北市": [
        _law("taipei", TAIPEI, "taipei", "FL004106", "臺北市建築管理自治條例"),
        _law("taipei", TAIPEI, "taipei", "FL003962", "臺北市土地使用分區管制自治條例"),
        _law("taipei", TAIPEI, "taipei", "FL004107", "臺北市畸零地使用自治條例"),
        _law("taipei", TAIPEI, "taipei", "FL075334", "臺北市綠建築自治條例"),
    ],
    "臺中市": [
        _law("taichung", TAICHUNG, "glrs", "GL002282", "臺中市建築管理自治條例"),
        _law("taichung", TAICHUNG, "glrs", "GL002020", "都市計畫法臺中市施行自治條例"),
        _law("taichung", TAICHUNG, "glrs", "GL001077", "臺中市畸零地使用自治條例"),
        _law("taichung", TAICHUNG, "glrs", "GL001045", "臺中市建築物附建防空避難設備或停車空間繳納代金及管理使用自治條例"),
    ],
    "臺南市": [
        _law("tainan", TAINAN, "glrs", "GL000154", "臺南市建築管理自治條例"),
    ],
    "苗栗縣": [
        _law("miaoli", MIAOLI, "glrs", "FL026450", "苗栗縣建築管理自治條例"),
    ],
}


def national_by_id():
    return {e["id"]: e for e in NATIONAL}


def local_for(region):
    return LOCAL.get(region, [])


def all_entries(region=None):
    return NATIONAL + local_for(region)


def every_entry():
    """National laws plus every collected county. The web page ships all of them."""
    return NATIONAL + [e for entries in LOCAL.values() for e in entries]
