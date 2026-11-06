import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bca import cli, config, fetch, search, store  # noqa: E402

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

TAICHUNG_PAGE = """
<tr><th>修正日期：</th><td>民國 112 年 03 月 31 日</td></tr>
<table id="ctl00_cp_content_tableLawArticleBasic" class="table">
<tr><td colspan="2" class="th law-char-2">第一章  總則</td></tr>
<tr><td class="th"></td><td><div class="ClearCss"><span>第一條　　本自治條例依建築法第一百零一條規定制定<br>
&nbsp;&nbsp;&nbsp; 之。</span></div></td></tr>
<tr><td class="th"></td><td><div class="ClearCss"><span>第二條　&nbsp; 申請人應依下列規定辦理：<br>
&nbsp; 一、依<br>
&nbsp; 第三十六條 規定申請。<br>
&nbsp; 二、其他。</span></div></td></tr>
<tr><td colspan="2" class="th law-char-2">第二章　　建築許可</td></tr>
<tr><td class="th"></td><td><div class="ClearCss">第二條之一　　之前的條文。</div></td></tr>
<tr><td class="th"></td><td><div class="ClearCss">第一百條　　不是下一條，跳太遠。</div></td></tr>
<tr><td class="th"></td><td><div class="ClearCss">第三條　　最後一條。</div></td></tr>
</table>
"""

TAINAN_PAGE = """
<tr><th>修正日期：</th>
<td>民國 107 年 07 月 12 日</td></tr>
<div id="ctl00_cp_content_divLawContent08" class="ClearCss">第　九　條　　本自治條例依建築法規定<br>
　　　　　制定之。<br>
第　十　條　　第十條。<br>
第 十一 條　　第十一條。<br>
</div>
"""

TAIPEI_PAGE = """
<label fix="">修正日期</label></div><div class="col-input"><dfn>&#x6C11;&#x570B; 108 &#x5E74; 02 &#x6708; 22 &#x65E5;</dfn>
<ul class="law law-content"><li class="chapter-2">第一章  總則</li>
<li><div class="row"><div class="col-no">第 2 條</div>
<div class="col-data"><div class="law-articlepre">用語定義如下：
一  出入通路：指寬度在三．五公尺以上，且非屬防火巷並提供
    建築物使用為出入之通路。</div>

</div><div class="col-link"><a href="x">相關SOP</a></div></div></li>
<li><div class="row"><div class="col-no">第 31-1 條</div>
<div class="col-data"><div class="law-articlepre">外牆定期診斷。</div></div></div></li></ul>
"""


class ParseTests(unittest.TestCase):
    def test_moj_labels_chapter_and_section(self):
        law = fetch.parse_moj_law(MOJ_RAW, ENTRY)
        self.assertEqual(law["amended"], "20260101")
        self.assertEqual([a["article"] for a in law["articles"]], ["第 1 條", "第 2 條"])
        self.assertIn("基地", law["articles"][0]["section"])
        self.assertEqual(law["articles"][1]["section"], "")  # a new chapter resets the section
        self.assertNotIn("\r", law["articles"][0]["text"])

    def test_zh_numbers(self):
        self.assertEqual([fetch.zh_to_int(x) for x in ["一", "十", "十一", "二十", "一百零一", "12"]], [1, 10, 11, 20, 101, 12])

    def test_taichung_table(self):
        law = fetch.parse_glrs(TAICHUNG_PAGE, {"id": "t", "name": "中", "url": "u"})
        a = law["articles"]
        self.assertEqual(law["amended"], "20230331")
        self.assertEqual([x["article"] for x in a], ["第 1 條", "第 2 條", "第 2-1 條", "第 3 條"])
        self.assertEqual(a[0]["text"], "本自治條例依建築法第一百零一條規定制定之。")
        self.assertIn("第三十六條 規定申請", a[1]["text"])  # a reference at the start of a line is not an article
        self.assertTrue(a[1]["text"].endswith("二、其他。"))  # the article before a chapter heading keeps its text
        self.assertIn("建築許可", a[2]["chapter"])
        self.assertIn("跳太遠", a[2]["text"])  # 第一百條 after 第二條之一 is too big a jump to be a new article

    def test_tainan_spaced_numbers(self):
        law = fetch.parse_glrs(TAINAN_PAGE, {"id": "n", "name": "南", "url": "u"})
        self.assertEqual([x["article"] for x in law["articles"]], ["第 9 條", "第 10 條", "第 11 條"])
        self.assertEqual(law["articles"][0]["text"], "本自治條例依建築法規定制定之。")

    def test_taipei(self):
        law = fetch.parse_taipei(TAIPEI_PAGE, {"id": "p", "name": "北", "url": "u"})
        a = law["articles"]
        self.assertEqual(law["amended"], "20190222")
        self.assertEqual([x["article"] for x in a], ["第 2 條", "第 31-1 條"])
        self.assertEqual(a[0]["text"], "用語定義如下：\n一  出入通路：指寬度在三．五公尺以上，且非屬防火巷並提供建築物使用為出入之通路。")
        self.assertIn("總則", a[1]["chapter"])

    def test_unwrap_keeps_tables(self):
        table = "│住宅區│百分之四十│\n│商業區│百分之六十│"
        self.assertEqual(fetch.unwrap(table), table)

    def test_law_table_rows(self):
        page = TAIPEI_PAGE.replace(
            "外牆定期診斷。",
            "不得超過下表規定：\n<table border=\"1\"><tbody>\n<tr>\n<td>\n<p>種別</p>\n</td>\n<td><p>建蔽率</p></td>\n</tr>\n"
            "<tr><td><p>第二條</p></td><td><p>百分之三十</p></td></tr></tbody></table>\n表外文字。",
        )
        text = fetch.parse_taipei(page, {"id": "p", "name": "北", "url": "u"})["articles"][1]["text"]
        self.assertEqual(text, "不得超過下表規定：\n種別 | 建蔽率\n第二條 | 百分之三十\n表外文字。")

    def test_table_inside_glrs_layout_table(self):
        inner = "<table><tr><td>第三條</td><td>百分之五十</td></tr></table>"
        page = TAICHUNG_PAGE.replace("二、其他。", "二、其他：" + inner)
        a = fetch.parse_glrs(page, {"id": "t", "name": "中", "url": "u"})["articles"]
        self.assertEqual([x["article"] for x in a], ["第 1 條", "第 2 條", "第 2-1 條", "第 3 條"])
        self.assertIn("第三條 | 百分之五十", a[1]["text"])  # a row is not mistaken for an article

    def test_roc_date(self):
        self.assertEqual(fetch.roc_to_ymd("民國 114 年 05 月 07 日"), "20250507")

    def test_miaoli_page(self):
        law = fetch.parse_glrs(MIAOLI_PAGE, {"id": "m", "name": "苗栗", "url": "u"})
        self.assertEqual(law["amended"], "20250507")
        self.assertEqual([a["article"] for a in law["articles"]], ["第 1 條", "第 2-1 條"])
        self.assertEqual(law["articles"][1]["text"], "建築基地未臨接建築線，不得建築。")  # hard wrap rejoined


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


class JudgeTests(unittest.TestCase):
    def test_verdict_tolerates_markdown(self):
        for text, want in [("PASS\n理由", True), ("**PASS**\n理由", True), ("判定：PASS", True),
                           ("FAIL\n沒有 PASS 的條件", False), ("**FAIL**", False), ("", False)]:
            self.assertEqual(cli.judge_passed(text), want, text)


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
