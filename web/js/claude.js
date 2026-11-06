// Minimal Anthropic Messages API client for the browser. The key never leaves this page
// except in the request to api.anthropic.com.

const API = "https://api.anthropic.com/v1/messages";
export const MODELS = { fast: "claude-haiku-5-5", smart: "claude-sonnet-5-5" };

export class ClaudeError extends Error {
  constructor(message, kind) {
    super(message);
    this.kind = kind; // "auth" | "rate" | "credit" | "network" | "other"
  }
}

async function failure(res) {
  let detail = "";
  try {
    detail = (await res.json())?.error?.message ?? "";
  } catch {}
  if (res.status === 401 || res.status === 403) return new ClaudeError("API key 無效或沒有權限，請檢查後再試。", "auth");
  if (res.status === 429) return new ClaudeError("請求太頻繁或額度用完，請稍後再試。", "rate");
  if (/credit balance/i.test(detail)) return new ClaudeError("這組 API key 的餘額不足，請到 console.anthropic.com 儲值。", "credit");
  return new ClaudeError(`API 回應錯誤（${res.status}）${detail ? "：" + detail : ""}`, "other");
}

/**
 * Ask Claude. With onDelta, streams and calls onDelta(textSoFar); always resolves to the full text.
 */
export async function complete({ key, tier, prompt, system, onDelta, signal, maxTokens = 4096 }) {
  const body = { model: MODELS[tier], max_tokens: maxTokens, messages: [{ role: "user", content: prompt }] };
  if (system) body.system = system;
  if (onDelta) body.stream = true;

  let res;
  try {
    res = await fetch(API, {
      method: "POST",
      signal,
      headers: {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        // Required by Anthropic for calls made directly from a browser with the user's own key.
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: JSON.stringify(body),
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ClaudeError("連不上 Anthropic，請檢查網路。", "network");
  }
  if (!res.ok) throw await failure(res);

  if (!onDelta) {
    const data = await res.json();
    const text = (data.content ?? []).filter((b) => b.type === "text").map((b) => b.text).join("").trim();
    if (!text) throw new ClaudeError("模型沒有回傳文字。", "other");
    return text;
  }

  // Server-sent events: lines like `data: {...}`; text arrives in content_block_delta events.
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line.startsWith("data:")) continue;
      let event;
      try {
        event = JSON.parse(line.slice(5));
      } catch {
        continue;
      }
      if (event.type === "content_block_delta" && event.delta?.type === "text_delta") {
        text += event.delta.text;
        onDelta(text);
      } else if (event.type === "error") {
        throw new ClaudeError(event.error?.message ?? "串流中斷", "other");
      }
    }
  }
  if (!text.trim()) throw new ClaudeError("模型沒有回傳文字。", "other");
  return text.trim();
}
