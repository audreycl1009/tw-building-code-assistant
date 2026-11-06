"""Talk to Claude. Two ways, so each user brings their own access:

- "claude": the `claude` command (Claude Code) logged in with your Claude account. No API key.
- "api":    the Anthropic API with your own ANTHROPIC_API_KEY (pay per use; a chat subscription is NOT a key).

backend "auto" (default) uses `claude` if it is installed, otherwise the API if a key is set.
"""
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

MODELS = {"fast": ("haiku", "claude-haiku-5-5"), "smart": ("sonnet", "claude-sonnet-5-5")}


class LLMError(RuntimeError):
    pass


def resolve_backend(choice="auto"):
    if choice in ("claude", "api"):
        return choice
    if shutil.which("claude"):
        return "claude"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    raise LLMError(
        "找不到可用的 Claude。請擇一：\n"
        "  1. 安裝 Claude Code 並登入（https://claude.com/claude-code），或\n"
        "  2. 設定環境變數 ANTHROPIC_API_KEY（到 console.anthropic.com 申請，按用量付費）。"
    )


def complete(prompt, tier="fast", system=None, backend="auto", timeout=300):
    backend = resolve_backend(backend)
    if backend == "claude":
        return _via_cli(prompt, MODELS[tier][0], system, timeout)
    return _via_api(prompt, MODELS[tier][1], system, timeout)


def _via_cli(prompt, model, system, timeout):
    # Run from a temp dir with tools and skills off, so it acts as a plain chat model.
    cmd = ["claude", "-p", "--model", model, "--tools", "", "--disable-slash-commands"]
    if system:
        cmd += ["--system-prompt", system]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
    if r.returncode != 0 or not r.stdout.strip():
        raise LLMError(f"claude 指令失敗：{(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _via_api(prompt, model, system, timeout):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("backend 設為 api，但沒有 ANTHROPIC_API_KEY")
    body = {"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception as e:
        raise LLMError(f"API 呼叫失敗：{e}") from e
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    if not text:
        raise LLMError(f"API 沒有回文字（stop_reason={data.get('stop_reason')}）")
    return text
