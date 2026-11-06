// The question-answering pipeline. Same steps as bca/assistant.py:
//   rewrite (Haiku) -> several BM25 searches merged -> answer (Sonnet) from those articles only.

import { complete } from "./claude.js";
import { Index, excerpt } from "./search.js";

export class Engine {
  constructor(laws, prompts, region, localIds = []) {
    this.laws = laws;
    this.prompts = prompts;
    this.region = region;
    this.index = new Index(laws);
    // The region's ordinances also get an index of their own. Word weights are then computed among
    // local articles only, so a few hundred of them are not drowned by national law.
    const ids = new Set(localIds);
    this.localIndex = new Index(laws.filter((l) => ids.has(l.id)));
    this.docPosition = new Map(this.index.docs.map((d, i) => [`${d.lawId}|${d.article}`, i]));
  }

  system() {
    const laws = this.laws.map((l) => `- ${l.name}（${l.amended}）`).join("\n");
    return this.prompts.system
      .replace("{laws}", () => laws)
      .replace("{region}", () => this.region || "未指定（只有全國法規）");
  }

  glossaryTerms(question) {
    return Object.entries(this.prompts.glossary)
      .filter(([k]) => question.includes(k))
      .map(([, v]) => v)
      .join(" ");
  }

  async rewrite(question, key, signal) {
    const text = await complete({
      key,
      signal,
      tier: "fast",
      prompt: this.prompts.rewrite_prompt.replace("{question}", () => question),
    });
    return text.split("\n").pop().trim();
  }

  /** Several searches merged (the local ordinances get their own, so national law cannot drown
   *  them out), then the opening (scope) articles of laws with several hits. */
  retrieve(question, terms) {
    const extra = this.glossaryTerms(question);
    const plain = this.index.search(`${question} ${extra}`, 12);
    const rewritten = this.index.search(`${terms} ${extra}`, 8);
    const glossary = extra ? this.index.search(extra, 5) : [];
    const local = this.localIndex
      .search(`${question} ${extra}`, 8)
      .map((i) => this.localIndex.docs[i])
      .map((d) => this.docPosition.get(`${d.lawId}|${d.article}`));
    const picked = [...new Set([...plain, ...rewritten, ...glossary, ...local])];
    return [...picked, ...this.scopeArticles(picked)].map((i) => this.index.docs[i]);
  }

  scopeArticles(picked, minHits = 3, firstN = 3, maxLen = 300) {
    const docs = this.index.docs;
    const perLaw = new Map();
    for (const i of picked) perLaw.set(docs[i].lawId, (perLaw.get(docs[i].lawId) ?? 0) + 1);
    const have = new Set(picked);
    const extra = [];
    for (const [lawId, n] of perLaw) {
      if (n < minHits) continue;
      const opening = [];
      for (let i = 0; i < docs.length && opening.length < firstN; i++) if (docs[i].lawId === lawId) opening.push(i);
      extra.push(...opening.filter((i) => !have.has(i) && docs[i].text.length <= maxLen));
    }
    return extra;
  }

  async answer(question, hits, key, onDelta, signal) {
    const parts = hits.map((d) => {
      const where = (d.chapter + (d.section ? " " + d.section : "")).trim() || "—";
      return `【${d.law} ${d.article}】（${where}）\n${excerpt(d.text, question)}`;
    });
    return complete({
      key,
      signal,
      tier: "smart",
      system: this.system(),
      prompt: `條文：\n${parts.join("\n\n")}\n\n問題：${question}`,
      onDelta,
    });
  }
}
