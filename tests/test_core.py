import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bca import config, fetch, search, store  # noqa: E402

MOJ_RAW = {
    "LawURL": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=X1",
    "LawModifiedDate": "20260101",
    "LawArticles": [
        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "   第 一 章 總則"},
        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "      第 一 節 基地"},
        {"ArticleType": "A", "ArticleNo": "第 1 條", "ArticleContent": "欄桿高度不得小於一‧一○公尺。\r\n第二行"},
        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "   第 二 章 設備"},
        {"ArticleType": "A", "ArticleNo": "第 2 條", "ArticleContent": "浴廁天花板淨高二‧一公尺。"},
    ],
}
ENTRY = {"id": "X1", "name": "測試法", "kind": "order"}

MIAOLI_PAGE = """
<tr><th>修正日期：</th>
<td>
    民國 114 年 05 月 07 日
</td></tr>
<div id="ctl00_cp_content_divLawContent08" class="ClearCss">
<p>第 1 條&nbsp;&nbsp;&nbsp;<br>
本自治條例依建築法制定。<br>
<br>
<br>
第 2-1 條<br>
建築基地未臨接建築線，<br>
不得建築。<br>
</p></div>
"""


class ParseTests(unittest.TestCase):
    def test_moj_labels_chapter_and_section(self):
        law = fetch.parse_moj_law(MOJ_RAW, ENTRY)
        self.assertEqual(law["amended"], "20260101")
        self.assertEqual([a["article"] for a in law["articles"]], ["第 1 條", "第 2 條"])
        self.assertIn("基地", law["articles"][0]["section"])
        self.assertEqual(law["articles"][1]["section"], "")  # a new chapter resets the section
        self.assertNotIn("\r", law["articles"][0]["text"])

    def test_roc_date(self):
        self.assertEqual(fetch.roc_to_ymd("民國 114 年 05 月 07 日"), "20250507")

    def test_miaoli_page(self):
        law = fetch.parse_miaoli(MIAOLI_PAGE, {"id": "m", "name": "苗栗", "url": "u"})
        self.assertEqual(law["amended"], "20250507")
        self.assertEqual([a["article"] for a in law["articles"]], ["第 1 條", "第 2-1 條"])
        self.assertEqual(law["articles"][1]["text"], "建築基地未臨接建築線，\n不得建築。")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BCA_HOME"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("BCA_HOME", None)
        self.tmp.cleanup()

    def test_versions_and_pin(self):
        old = fetch.parse_moj_law(MOJ_RAW, ENTRY)
        new = dict(old, amended="20270101")
        self.assertTrue(store.save(old))
        self.assertFalse(store.save(old))  # same version twice is a no-op
        self.assertTrue(store.save(new))
        self.assertEqual(store.versions("X1"), ["20260101", "20270101"])
        self.assertEqual(store.load("X1")["amended"], "20270101")
        self.assertEqual(store.load("X1", pin="20260101")["amended"], "20260101")
        self.assertEqual(store.load("X1", pin="19990101")["amended"], "20270101")  # bad pin -> latest

    def test_config_roundtrip(self):
        self.assertFalse(config.is_set_up())
        config.save({"region": "苗栗縣"})
        self.assertEqual(config.load()["region"], "苗栗縣")
        self.assertEqual(config.load()["backend"], "auto")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.index = search.Index([fetch.parse_moj_law(MOJ_RAW, ENTRY)])

    def test_variant_characters_match(self):
        top = self.index.search("欄杆高度")  # 杆 typed, 桿 printed
        self.assertEqual(self.index.docs[top[0]]["article"], "第 1 條")

    def test_rank_of(self):
        self.assertEqual(self.index.rank_of("浴廁天花板", "X1", "第 2 條"), 1)

    def test_excerpt_keeps_matching_lines(self):
        text = "標題\n" + "\n".join(f"無關內容第{i}行" * 5 for i in range(200)) + "\n雨遮突出一公尺"
        out = search.excerpt(text, "雨遮突出", limit=300)
        self.assertIn("雨遮突出一公尺", out)
        self.assertTrue(out.startswith("標題"))
        self.assertLess(len(out), 450)


if __name__ == "__main__":
    unittest.main()
