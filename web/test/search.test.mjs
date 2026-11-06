// Run: node --test web/test/
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Index, bigrams, excerpt } from "../js/search.js";

const load = (f) => JSON.parse(readFileSync(new URL("../data/" + f, import.meta.url), "utf-8"));
const laws = [...load("national.json"), ...load("region-苗栗縣.json")];
const index = new Index(laws);
const SHI = "D0070115"; // 建築技術規則建築設計施工編

test("variant characters match (欄杆 typed, 欄桿 printed)", () => {
  assert.deepEqual(bigrams("欄桿"), bigrams("欄杆"));
});

test("known questions find their article near the top", () => {
  const cases = [
    ["陽台欄杆要做多高？ 陽臺", SHI, "第 38 條", 3],
    ["廁所的天花板最低可以做多低？ 浴廁", SHI, "第 32 條", 3],
    ["房子沒有使用執照可以接水接電嗎？", "D0070109", "第 73 條", 5],
    ["在苗栗縣申請指定建築線要繳多少規費？多久會審完？", "miaoli-FL026450", "第 2 條", 3],
  ];
  for (const [q, law, art, max] of cases) {
    const r = index.rankOf(q, law, art);
    assert.ok(r !== null && r <= max, `${q} -> ${art} rank ${r}`);
  }
});

test("excerpt keeps the matching line of a long article", () => {
  const text = "標題\n" + Array.from({ length: 200 }, (_, i) => `無關內容第${i}行`.repeat(5)).join("\n") + "\n雨遮突出一公尺";
  const out = excerpt(text, "雨遮突出", 300);
  assert.ok(out.startsWith("標題") && out.includes("雨遮突出一公尺") && out.length < 450);
});

test("doc counts match the exported laws", () => {
  assert.equal(index.docs.length, laws.reduce((n, l) => n + l.articles.length, 0));
});
