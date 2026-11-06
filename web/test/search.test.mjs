// Run: node --test web/test/
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Index, bigrams, excerpt } from "../js/search.js";
import { Engine } from "../js/engine.js";

const load = (f) => JSON.parse(readFileSync(new URL("../data/" + f, import.meta.url), "utf-8"));
const regions = ["臺北市", "臺中市", "臺南市", "苗栗縣"].flatMap((r) => load(`region-${r}.json`));
const laws = [...load("national.json"), ...regions];
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

test("the index of a region's own ordinances finds what national law drowns out", () => {
  const cases = [
    ["臺北市", "臺北市第三種住宅區的建蔽率和容積率是多少？", "taipei-FL003962", "第 10 條"],
    ["臺北市", "在臺北市，基地臨路多窄會被算成畸零地？", "taipei-FL004107", "第 3 條"],
    ["臺中市", "臺中市住宅區的建蔽率最高是多少？", "taichung-GL002020", "第 43 條"],
    ["臺南市", "在臺南申請指定建築線要多久才會辦好？", "tainan-GL000154", "第 3 條"],
  ];
  for (const [region, q, lawId, article] of cases) {
    const idx = new Index(load(`region-${region}.json`));
    const top = idx.search(q, 8);
    assert.ok(top.some((i) => idx.docs[i].lawId === lawId && idx.docs[i].article === article), `${q} -> ${article}`);
  }
});

test("the web engine retrieves local ordinances for the selected region only", () => {
  const prompts = load("prompts.json");
  const engineFor = (region) => {
    const local = load(`region-${region}.json`);
    return new Engine([...load("national.json"), ...local], prompts, region, local.map((l) => l.id));
  };
  const has = (hits, lawId, article) => hits.some((d) => d.lawId === lawId && d.article === article);

  const taichung = engineFor("臺中市").retrieve("臺中市住宅區的建蔽率最高是多少？", "住宅區 建蔽率");
  assert.ok(has(taichung, "taichung-GL002020", "第 43 條"));
  assert.ok(taichung.every((d) => !d.lawId.startsWith("taipei-")));

  const taipei = engineFor("臺北市").retrieve("在臺北市，基地臨路多窄會被算成畸零地？", "畸零地 建築線");
  assert.ok(has(taipei, "taipei-FL004107", "第 3 條"));
});

test("excerpt keeps the matching line of a long article", () => {
  const text = "標題\n" + Array.from({ length: 200 }, (_, i) => `無關內容第${i}行`.repeat(5)).join("\n") + "\n雨遮突出一公尺";
  const out = excerpt(text, "雨遮突出", 300);
  assert.ok(out.startsWith("標題") && out.includes("雨遮突出一公尺") && out.length < 450);
});

test("every region file lists its laws in the manifest", () => {
  const manifest = load("manifest.json");
  assert.deepEqual(Object.keys(manifest.regions).sort(), ["臺中市", "臺北市", "臺南市", "苗栗縣"].sort());
  for (const [name, info] of Object.entries(manifest.regions)) {
    assert.deepEqual(load(info.file).map((l) => l.name), info.laws, name);
  }
});

test("no article is empty, and article numbers are digits (citations in the page need them)", () => {
  for (const law of regions) {
    for (const [article, , , text] of law.articles) {
      assert.match(article, /^第 \d+(-\d+)? 條$/, `${law.name} ${article}`);
      assert.ok(text.trim(), `${law.name} ${article} is empty`);
    }
  }
});

test("doc counts match the exported laws", () => {
  assert.equal(index.docs.length, laws.reduce((n, l) => n + l.articles.length, 0));
});
