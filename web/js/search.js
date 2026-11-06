// Keyword search (BM25 over character bigrams). Same algorithm as bca/search.py.
// Pure functions, no DOM, so it can be tested in Node.

// Variant characters people type vs. what the regulation prints (臺/台, 欄桿/欄杆 ...).
const NORMALIZE = { 臺: "台", 桿: "杆", 廁: "厕", 裡: "里", 裏: "里", 線: "线", 衞: "卫", 衛: "卫" };

export function bigrams(text) {
  const chars = [...text].map((c) => NORMALIZE[c] ?? c).filter((c) => !/\s/.test(c));
  const out = [];
  for (let i = 0; i < chars.length - 1; i++) out.push(chars[i] + chars[i + 1]);
  return out;
}

export class Index {
  // laws: [{id, name, amended, articles: [[article, chapter, section, text], ...]}]
  constructor(laws) {
    this.docs = [];
    for (const law of laws) {
      for (const [article, chapter, section, text] of law.articles) {
        this.docs.push({ article, chapter, section, text, lawId: law.id, law: law.name, amended: law.amended });
      }
    }
    this.docLen = [];
    this.postings = new Map(); // bigram -> [[doc index, count], ...]
    this.docs.forEach((d, i) => {
      const counts = new Map();
      let total = 0;
      for (const bg of bigrams(d.chapter + d.section + d.text)) {
        counts.set(bg, (counts.get(bg) ?? 0) + 1);
        total++;
      }
      this.docLen.push(total);
      for (const [bg, n] of counts) {
        if (!this.postings.has(bg)) this.postings.set(bg, []);
        this.postings.get(bg).push([i, n]);
      }
    });
    this.avgLen = this.docs.length ? this.docLen.reduce((a, b) => a + b, 0) / this.docs.length : 1;
  }

  /** Top-k doc indices, best first. */
  search(query, k = 10, k1 = 1.5, b = 0.75) {
    const n = this.docs.length;
    const scores = new Map();
    for (const bg of new Set(bigrams(query))) {
      const plist = this.postings.get(bg);
      if (!plist) continue;
      const idf = Math.log(1 + (n - plist.length + 0.5) / (plist.length + 0.5));
      for (const [i, tf] of plist) {
        const s = (idf * tf * (k1 + 1)) / (tf + k1 * (1 - b + (b * this.docLen[i]) / this.avgLen));
        scores.set(i, (scores.get(i) ?? 0) + s);
      }
    }
    return [...scores.keys()].sort((a, c) => scores.get(c) - scores.get(a)).slice(0, k);
  }

  /** 1-based rank of an article for a query, or null. Used by tests. */
  rankOf(query, lawId, article) {
    const ranking = this.search(query, this.docs.length);
    const pos = ranking.findIndex((i) => this.docs[i].lawId === lawId && this.docs[i].article === article);
    return pos < 0 ? null : pos + 1;
  }
}

/** Keep long articles readable: header line plus the lines that best match the query, in order. */
export function excerpt(text, query, limit = 3000) {
  if (text.length <= limit) return text;
  const lines = text.split("\n");
  const q = new Set(bigrams(query));
  const overlap = (line) => bigrams(line).filter((g) => q.has(g)).length; // approximates |q ∩ set(line)|
  const order = [...lines.keys()].slice(1).sort((a, b) => overlap(lines[b]) - overlap(lines[a]));
  const keep = new Set([0]);
  let used = lines[0].length;
  for (const i of order) {
    if (used + lines[i].length > limit) continue;
    keep.add(i);
    used += lines[i].length;
  }
  const out = [...keep].sort((a, b) => a - b).map((i) => lines[i]);
  if (keep.size < lines.length) out.push("（本條較長，以上為與問題最相關的款項，其餘省略）");
  return out.join("\n");
}
