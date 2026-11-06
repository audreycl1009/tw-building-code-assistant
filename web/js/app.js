import { ClaudeError } from "./claude.js";
import { Engine } from "./engine.js";

const $ = (id) => document.getElementById(id);
const KEY_STORE = "bca.apiKey";
const REGION_STORE = "bca.region";

const state = { manifest: null, prompts: null, national: null, regionLaws: {}, engine: null, region: "", regionRequest: 0, running: null };

/* ---------- small helpers ---------- */

const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** '20250507' -> '民國 114/05/07' */
function rocDate(ymd) {
  if (!/^\d{8}$/.test(ymd)) return ymd;
  return `民國 ${Number(ymd.slice(0, 4)) - 1911}/${ymd.slice(4, 6)}/${ymd.slice(6)}`;
}

function normArticle(n) {
  return `第 ${n} 條`;
}

/* ---------- API key storage (browser only) ---------- */

function loadKey() {
  const remembered = localStorage.getItem(KEY_STORE);
  if (remembered) return { key: remembered, remember: true };
  return { key: sessionStorage.getItem(KEY_STORE) || "", remember: false };
}

function persistKey() {
  const key = $("key").value.trim();
  localStorage.removeItem(KEY_STORE);
  sessionStorage.removeItem(KEY_STORE);
  if (key) (($("remember").checked ? localStorage : sessionStorage)).setItem(KEY_STORE, key);
  $("key-clear").hidden = !key;
}

function showKeyError(msg) {
  const el = $("key-error");
  el.hidden = !msg;
  el.textContent = msg || "";
  $("key").setAttribute("aria-invalid", msg ? "true" : "false");
}

/* ---------- data loading ---------- */

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function boot() {
  try {
    const [manifest, prompts] = await Promise.all([getJSON("data/manifest.json"), getJSON("data/prompts.json")]);
    state.manifest = manifest;
    state.prompts = prompts;
    state.national = await getJSON("data/" + manifest.national);
  } catch (e) {
    const boot = $("boot");
    boot.classList.add("bad");
    boot.textContent = location.protocol === "file:"
      ? "無法直接用檔案開啟。請在專案資料夾執行  python3 -m http.server -d web  再開 http://localhost:8000"
      : "載入法規資料失敗，請重新整理。";
    return;
  }
  fillRegions();
  await applyRegion(localStorage.getItem(REGION_STORE) || "");
  $("boot").hidden = true;
  $("go").disabled = false;
}

function fillRegions() {
  const sel = $("region");
  const opts = [new Option("只用全國法規", "")];
  for (const c of state.manifest.counties) {
    const has = c in state.manifest.regions;
    opts.push(new Option(has ? `${c}（含自治條例）` : `${c}（自治條例尚未收錄）`, c));
  }
  sel.replaceChildren(...opts);
}

async function applyRegion(region) {
  if (region && !state.manifest.counties.includes(region)) region = "";
  const info = state.manifest.regions[region];
  const request = ++state.regionRequest; // a slower, older request must not override a newer choice
  if (info && !state.regionLaws[region]) state.regionLaws[region] = await getJSON("data/" + info.file);
  if (request !== state.regionRequest) return;
  state.region = region;
  $("region").value = region;
  localStorage.setItem(REGION_STORE, region);

  const local = info ? state.regionLaws[region] : [];
  state.engine = new Engine([...state.national, ...local], state.prompts, region, local.map((l) => l.id));
  $("region-note").textContent = !region
    ? "選擇地區後會一併載入該縣市的建築自治條例。"
    : info ? `已載入${region}的 ${info.laws.length} 部自治條例。` : `${region}的自治條例尚未收錄，目前只用全國法規；地方規定請另向當地主管機關確認。`;
  renderLaws(local.map((l) => l.id));
}

function renderLaws(localIds) {
  const laws = state.engine.laws;
  $("laws-count").textContent = `${laws.length} 部`;
  const items = laws.map((l) => {
    const li = document.createElement("li");
    const name = document.createElement("span");
    if (localIds.includes(l.id)) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "地方";
      name.append(tag);
    }
    name.append(l.name);
    const date = document.createElement("span");
    date.className = "date";
    date.textContent = rocDate(l.amended);
    li.append(name, date);
    return li;
  });
  $("laws").replaceChildren(...items);
  $("data-date").textContent = `資料產生於 ${state.manifest.generated}；日期為各法規最後修正日。`;
}

/* ---------- rendering ---------- */

function renderMarkdown(src) {
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  let html = "";
  let list = null;
  const close = () => {
    if (list) html += `</${list}>`;
    list = null;
  };
  const open = (kind) => {
    if (list !== kind) {
      close();
      html += `<${kind}>`;
      list = kind;
    }
  };
  for (const raw of escapeHtml(src).split("\n")) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) close();
    else if ((m = line.match(/^\s*#{1,4}\s+(.*)/))) (close(), (html += `<h4>${inline(m[1])}</h4>`));
    else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) (open("ul"), (html += `<li>${inline(m[1])}</li>`));
    else if ((m = line.match(/^\s*\d+[.、)]\s+(.*)/))) (open("ol"), (html += `<li>${inline(m[1])}</li>`));
    else (close(), (html += `<p>${inline(line.trim())}</p>`));
  }
  close();
  return html;
}

/** Regex that finds "<law name> 第 N 條" in text. Longest names first so 施行細則 wins over its parent law. */
function citationRegex() {
  const names = state.engine.laws.map((l) => l.name).sort((a, b) => b.length - a.length);
  const esc = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`(${esc.join("|")})\\s*第\\s*(\\d+(?:-\\d+)?)\\s*條(?:\\s*第\\s*\\d+\\s*項)?(?:\\s*第\\s*\\d+\\s*款)?`, "g");
}

function renderAnswer(text, final) {
  const el = $("answer");
  let html = renderMarkdown(text);
  html = html.replace(citationRegex(), (whole, law, n) => {
    const key = `${law}|${normArticle(n)}`;
    return `<button type="button" class="cite" data-ref="${escapeHtml(key)}">${whole}</button>`;
  });
  el.innerHTML = html;
  el.classList.toggle("streaming", !final);
  el.hidden = false;
}

function citedKeys(text) {
  const keys = new Set();
  for (const m of text.matchAll(citationRegex())) keys.add(`${m[1]}|${normArticle(m[2])}`);
  return keys;
}

function refItem(d, isCited) {
  const det = document.createElement("details");
  det.dataset.ref = `${d.law}|${d.article}`;
  if (isCited) det.className = "cited";
  const sum = document.createElement("summary");
  const title = document.createElement("div");
  title.className = "ref-title";
  const no = Object.assign(document.createElement("span"), { className: "ref-no", textContent: d.article });
  const law = Object.assign(document.createElement("span"), { className: "ref-law", textContent: d.law });
  title.append(no, law);
  if (isCited) title.append(Object.assign(document.createElement("span"), { className: "ref-badge", textContent: "答案引用" }));
  const where = (d.chapter + " " + d.section).trim();
  if (where) title.append(Object.assign(document.createElement("span"), { className: "ref-where", textContent: `${where}　·　${rocDate(d.amended)}修正` }));
  sum.append(title);
  det.append(sum, Object.assign(document.createElement("p"), { className: "ref-text", textContent: d.text }));
  return det;
}

function renderRefs(hits, answerText) {
  const cited = citedKeys(answerText);
  const keyOf = (d) => `${d.law}|${d.article}`;
  const main = hits.filter((d) => cited.has(keyOf(d)));
  const rest = hits.filter((d) => !cited.has(keyOf(d)));

  const items = main.map((d) => refItem(d, true));
  if (rest.length) {
    const more = document.createElement("details");
    more.className = "more";
    more.id = "refs-more";
    const sum = Object.assign(document.createElement("summary"), { textContent: `其他檢索到的條文（${rest.length}）` });
    const inner = document.createElement("div");
    inner.className = "more-list";
    inner.append(...rest.map((d) => refItem(d, false)));
    more.append(sum, inner);
    items.push(more);
  }
  $("refs").replaceChildren(...items);
  $("refs-count").textContent = `${hits.length} 條`;
  $("refs-hint").textContent = main.length
    ? "琥珀色標記的是答案實際引用的條文；點答案裡的條號可跳到這裡。"
    : "答案沒有明確引用條文；以下是檢索到的相關條文。";
  $("refs-box").hidden = false;
  if (!main.length && rest.length) $("refs-more").open = true;

  const used = new Map();
  for (const d of hits) if (cited.has(keyOf(d))) used.set(d.law, d.amended);
  const v = $("versions");
  v.hidden = used.size === 0;
  v.textContent = used.size ? "答案參考的法規版本：" + [...used].map(([n, a]) => `${n}（${rocDate(a)}）`).join("、") : "";
}

function setStep(name, status) {
  for (const li of $("steps").children) {
    if (li.dataset.step === name) li.className = status;
  }
}

/* ---------- ask ---------- */

async function ask(question) {
  const key = $("key").value.trim();
  if (!key) {
    showKeyError("請先輸入你的 Anthropic API key。");
    $("key").focus();
    return;
  }
  showKeyError("");

  const ctl = new AbortController();
  state.running = ctl;
  setRunning(true);
  $("result").hidden = false;
  $("fail").hidden = true;
  $("answer").hidden = true;
  $("refs-box").hidden = true;
  $("versions").hidden = true;
  for (const s of ["rewrite", "search", "answer"]) setStep(s, "");
  $("result").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });

  let answerText = "";
  try {
    setStep("rewrite", "active");
    const terms = await state.engine.rewrite(question, key, ctl.signal);
    setStep("rewrite", "done");

    setStep("search", "active");
    const hits = state.engine.retrieve(question, terms);
    setStep("search", "done");

    setStep("answer", "active");
    answerText = await state.engine.answer(question, hits, key, (t) => renderAnswer(t, false), ctl.signal);
    renderAnswer(answerText, true);
    setStep("answer", "done");
    renderRefs(hits, answerText);
  } catch (e) {
    if (e.name === "AbortError") {
      setStep("answer", "");
      $("answer").classList.remove("streaming");
    } else {
      for (const s of ["rewrite", "search", "answer"]) if ($("steps").querySelector(`[data-step="${s}"]`).className === "active") setStep(s, "");
      $("answer").classList.remove("streaming");
      const msg = e instanceof ClaudeError ? e.message : "發生未預期的錯誤：" + e.message;
      $("fail").textContent = msg;
      $("fail").hidden = false;
      if (e instanceof ClaudeError && e.kind === "auth") showKeyError(msg);
    }
  } finally {
    state.running = null;
    setRunning(false);
  }
}

function setRunning(on) {
  const b = $("go");
  b.textContent = on ? "停止" : "提問";
  b.classList.toggle("stop", on);
  b.type = on ? "button" : "submit";
}

/* ---------- wiring ---------- */

function init() {
  const saved = loadKey();
  $("key").value = saved.key;
  $("remember").checked = saved.remember;
  $("key-clear").hidden = !saved.key;
  $("go").disabled = true;

  $("key").addEventListener("input", () => (showKeyError(""), persistKey()));
  $("remember").addEventListener("change", persistKey);
  $("key-clear").addEventListener("click", () => {
    $("key").value = "";
    $("remember").checked = false;
    persistKey();
    $("key").focus();
  });
  $("key-toggle").addEventListener("click", (ev) => {
    const show = $("key").type === "password";
    $("key").type = show ? "text" : "password";
    ev.currentTarget.setAttribute("aria-pressed", String(show));
    ev.currentTarget.setAttribute("aria-label", show ? "隱藏金鑰" : "顯示金鑰");
  });
  $("region").addEventListener("change", (ev) => applyRegion(ev.target.value));

  $("ask").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("q").value.trim();
    if (q && !state.running && state.engine) ask(q);
  });
  $("go").addEventListener("click", () => state.running?.abort());
  $("q").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) $("ask").requestSubmit();
  });
  for (const chip of document.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => {
      $("q").value = chip.textContent;
      $("q").focus();
    });
  }

  // Clicking a citation in the answer opens and highlights that article below.
  $("answer").addEventListener("click", (ev) => {
    const btn = ev.target.closest(".cite");
    if (!btn) return;
    const target = [...$("refs").querySelectorAll("details[data-ref]")].find((d) => d.dataset.ref === btn.dataset.ref);
    if (!target) return;
    target.closest("details.more")?.setAttribute("open", "");
    target.open = true;
    target.classList.remove("flash");
    void target.offsetWidth; // restart the animation
    target.classList.add("flash");
    target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
  });

  // Keep the law list open on desktop, collapsed on narrow screens.
  if (matchMedia("(max-width: 880px)").matches) $("laws-box").open = false;

  boot();
}

init();
