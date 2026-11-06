"""Command line: bca setup | update | laws | pin | ask | eval | export-web"""
import argparse
import json
import os
import shutil
import sys

from . import config, fetch, llm, registry, store

HERE = os.path.dirname(os.path.abspath(__file__))


def cmd_update(args):
    cfg = config.load()
    entries = registry.all_entries(cfg.get("region"))
    print(f"更新 {len(entries)} 部法規（地區：{cfg.get('region') or '只有全國法規'}）…")
    nat, err1 = fetch.fetch_moj([e for e in entries if "kind" in e])
    loc, err2 = fetch.fetch_local([e for e in entries if "source" in e])
    for law in nat + loc:
        new = store.save(law)
        vs = store.versions(law["id"])
        note = "新版本" if new and len(vs) > 1 else ("已下載" if new else "已是最新")
        print(f"  {note:6s} {law['name']}（{law['amended']}，{len(law['articles'])} 條）")
    for e in err1 + err2:
        print(f"  ⚠️  {e}")
    return 1 if (err1 or err2) and not (nat or loc) else 0


def cmd_setup(args):
    cfg = config.load()
    region = args.region
    if region is None and not args.yes:
        print("請選擇你要查的地區（會一併載入該縣市的建築自治條例）：")
        print("  0. 只用全國法規")
        for i, c in enumerate(registry.COUNTIES, 1):
            mark = "" if registry.local_for(c) else "（自治條例尚未收錄，只會用全國法規）"
            print(f"  {i}. {c}{mark}")
        raw = input("輸入編號（Enter = 0）：").strip() or "0"
        if not raw.isdigit() or int(raw) > len(registry.COUNTIES):
            print("輸入無效")
            return 2
        region = registry.COUNTIES[int(raw) - 1] if int(raw) else None
    if region is not None and region not in registry.COUNTIES:
        print(f"沒有這個地區：{region}")
        return 2
    cfg["region"] = region
    if args.backend:
        cfg["backend"] = args.backend
    try:
        print(f"AI 連線方式：{llm.resolve_backend(cfg['backend'])}")
    except llm.LLMError as e:
        print(f"⚠️  {e}\n（法規仍會先下載，之後設定好再提問即可）")
    config.save(cfg)
    if region and not registry.local_for(region):
        print(f"注意：{region} 的自治條例尚未收錄，目前只載入全國法規。")
    return cmd_update(args)


def cmd_laws(args):
    cfg = config.load()
    print(f"地區：{cfg.get('region') or '未指定'}　連線方式：{cfg.get('backend')}")
    for e in registry.all_entries(cfg.get("region")):
        vs = store.versions(e["id"])
        pin = cfg.get("pins", {}).get(e["id"])
        shown = pin if pin in vs else (vs[-1] if vs else None)
        pinned = "（已固定）" if pin in vs else ""
        extra = f"　可選版本：{', '.join(vs)}" if len(vs) > 1 else ""
        print(f"  {e['id']:16s} {e['name']}　{shown or '未下載'}{pinned}{extra}")


def cmd_pin(args):
    cfg = config.load()
    vs = store.versions(args.law_id)
    if args.version == "latest":
        cfg.get("pins", {}).pop(args.law_id, None)
    elif args.version in vs:
        cfg.setdefault("pins", {})[args.law_id] = args.version
    else:
        print(f"沒有這個版本。已下載的版本：{', '.join(vs) or '無'}")
        return 2
    config.save(cfg)
    print("已更新。")


def _compact(law):
    return {"id": law["id"], "name": law["name"], "amended": law["amended"], "url": law["source_url"],
            "articles": [[a["article"], a["chapter"].strip(), a["section"].strip(), a["text"]] for a in law["articles"]]}


def cmd_export_web(args):
    """Write the static data files the web page loads (web/data/*.json) from the local store."""
    import datetime
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    cfg = config.load()
    pins = cfg.get("pins", {})

    def dump(name, entries):
        laws = store.load_all(entries, pins)
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump([_compact(l) for l in laws], f, ensure_ascii=False, separators=(",", ":"))
        return laws

    national = dump("national.json", registry.NATIONAL)
    regions = {}
    for region, entries in registry.LOCAL.items():
        laws = dump(f"region-{region}.json", entries)
        if laws:
            regions[region] = {"file": f"region-{region}.json", "laws": [l["name"] for l in laws]}
    shutil.copyfile(os.path.join(HERE, "prompts.json"), os.path.join(out, "prompts.json"))
    manifest = {"generated": datetime.date.today().isoformat(), "national": "national.json",
                "counties": registry.COUNTIES, "regions": regions}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"輸出到 {out}：全國 {len(national)} 部，地區 {', '.join(regions) or '無'}")
    return 0


def _show(assistant, question):
    res = assistant.ask(question)
    print(f"\n搜尋詞：{res['terms']}")
    by_law = {}
    for d in res["hits"]:
        by_law.setdefault(d["law"], []).append(d["article"])
    print("參考條文：" + "；".join(f"{law} {'、'.join(arts)}" for law, arts in by_law.items()) + "\n")
    print(res["answer"])
    print("\n" + assistant.footer(res) + "\n")
    return res


def cmd_ask(args):
    from .assistant import Assistant
    a = Assistant()
    if args.question:
        _show(a, " ".join(args.question))
        return 0
    print("法規助理（Ctrl-C 離開）")
    try:
        while True:
            q = input("問法規> ").strip()
            if q:
                _show(a, q)
    except (KeyboardInterrupt, EOFError):
        print()
    return 0


JUDGE = """你在批改建築法規助理的答案。比對「助理答案」與「參考答案」。
- PASS：助理答案包含參考答案的所有關鍵數字與條件，且沒有與之矛盾的內容。
- FAIL：漏掉關鍵數字或條件，或與參考答案矛盾，或只說找不到。
第一行只寫 PASS 或 FAIL，第二行用一句話說明原因。

問題：{q}
參考答案：{ref}
助理答案：{ans}"""


def cmd_eval(args):
    from .assistant import Assistant
    a = Assistant()
    path = args.file or os.path.join(HERE, "eval_questions.json")
    questions = json.load(open(path, encoding="utf-8"))["questions"]
    if args.region_only:
        questions = [q for q in questions if q.get("needs_region") in (None, a.cfg.get("region"))]
    hit = passed = 0
    for q in questions:
        res = a.ask(q["question"])
        found = {(d["law_id"], d["article"]) for d in res["hits"]}
        ok = all((e["law"], e["article"]) in found for e in q["expected"])
        hit += ok
        line = f"{q['id']} 檢索{'✅' if ok else '❌'}"
        if args.judge:
            verdict = llm.complete(JUDGE.format(q=q["question"], ref=q["expected_answer"], ans=res["answer"]),
                                   "smart", backend=a.backend)
            good = verdict.strip().upper().startswith("PASS")
            passed += good
            line += f" 答案{'✅' if good else '❌'} {verdict.splitlines()[-1] if verdict.count(chr(10)) else ''}"
        print(f"{line}  {q['question']}")
    n = len(questions)
    print(f"\n檢索命中 {hit}/{n}" + (f"，答案通過 {passed}/{n}" if args.judge else ""))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="bca", description="台灣建築法規助理")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="選地區、下載法規")
    s.add_argument("--region", help="例如 苗栗縣")
    s.add_argument("--backend", choices=["auto", "claude", "api"])
    s.add_argument("--yes", action="store_true", help="不互動，只用全國法規（或搭配 --region）")
    s.set_defaults(fn=cmd_setup)
    sub.add_parser("update", help="重新下載，抓修正後的新版").set_defaults(fn=cmd_update)
    sub.add_parser("laws", help="列出已載入的法規與版本").set_defaults(fn=cmd_laws)
    s = sub.add_parser("pin", help="固定某部法規用舊版本")
    s.add_argument("law_id")
    s.add_argument("version", help="例如 20250513，或 latest")
    s.set_defaults(fn=cmd_pin)
    s = sub.add_parser("export-web", help="輸出網頁用的靜態資料")
    s.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "web", "data"))
    s.set_defaults(fn=cmd_export_web)
    s = sub.add_parser("ask", help="問問題（不給問題就進入對話）")
    s.add_argument("question", nargs="*")
    s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("eval", help="跑評測題")
    s.add_argument("--judge", action="store_true", help="另外請 Claude 批改答案內容")
    s.add_argument("--file")
    s.add_argument("--region-only", action="store_true", help="略過需要其他地區資料的題目")
    s.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    try:
        return args.fn(args) or 0
    except (RuntimeError, llm.LLMError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
