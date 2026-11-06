# 建築法規助理 building-code-assistant

用口語問台灣的建築法規，它會找出相關條文、整理答案並標出「哪部法規第幾條」。
**本機執行**：法規下載後存在你的電腦，AI 用你自己的 Claude 帳號（或自己的 API key），不需要任何共用伺服器。

> 這是輔助查詢工具，不是法律意見。實際認定以主管建築機關為準。

## 它做什麼

```
你的問題 ─▶ 改寫成法規用語 (Haiku) ─▶ 在所有已載入的法規裡找條文 (BM25) ─▶ 只根據這些條文回答 (Sonnet)
```

- 同時查**多層法規**：建築法、建築技術規則（總則／設計施工／構造／設備）、室內裝修管理辦法、使用類組及變更使用辦法、
  公寓大廈管理條例、都市計畫法等 19 部全國法規，加上你所選地區的**自治條例**。
- 答案要標出處；問題取決於**沒載入的法規**時，會明說「這點需要查閱○○，目前沒有載入」而不是猜。
- 每個答案附上所參考法規的**修正日期**，看得出資料新不新。
- 可以更新到最新修正版，也可以把某部法規**固定在舊版本**（例如查舊案）。

## 指令列版安裝

需要 Python 3.9 以上，沒有其他套件。

```bash
git clone <this repo> && cd building-code-assistant
python3 -m pip install -e .        # 之後可直接用 bca 指令；不安裝也能用 python3 -m bca
```

AI 連線方式二選一（`bca setup` 會告訴你偵測到哪一種）：

| 方式 | 怎麼設 | 費用 |
|---|---|---|
| Claude 帳號登入 | 安裝並登入 [Claude Code](https://claude.com/claude-code)，指令 `claude` 可用即可 | 用你的訂閱額度 |
| 自己的 API key | `export ANTHROPIC_API_KEY=...`（到 console.anthropic.com 申請） | 按用量，一題約 1–3 美分 |

> Claude 聊天訂閱**不是** API key；它們是兩個分開的計費。

## 使用

```bash
bca setup                      # 選地區、下載法規（首次一定要做）
bca ask "陽台欄杆要做多高？"      # 問一題
bca ask                        # 進入連續對話
bca laws                       # 看載入了哪些法規、哪個版本
bca update                     # 法規修正後，抓新版（舊版保留）
bca pin D0070115 20260223      # 把設計施工編固定在某個舊版；bca pin D0070115 latest 取消
```

資料放在 `~/.building-code-assistant/`（用環境變數 `BCA_HOME` 改位置）。

## 網頁版（純前端、開源）

`web/` 是一個**不需要後端**的靜態網頁：法規資料跟著網頁一起發佈，搜尋在你的瀏覽器裡執行，
AI 呼叫則是瀏覽器**直接**送到 `api.anthropic.com`，用的是你在頁面上輸入的 API key。

- API key 預設只存在這個分頁（關掉就沒了）；勾「記住在這個瀏覽器」才會存進 localStorage，也可以一鍵清除。
- 網頁有內容安全政策（CSP），只允許連到自己和 `api.anthropic.com`；沒有追蹤、沒有第三方腳本（只載入 Google Fonts 字型）。
- 提示詞與同義詞表與指令列版共用同一份（`bca/prompts.json`），兩邊行為一致。

**本機試用**（瀏覽器不能直接開檔案，要起一個靜態伺服器）：

```bash
python3 -m http.server -d web      # 然後開 http://localhost:8000
```

**更新網頁用的資料**（法規修正後）：

```bash
bca update && bca export-web       # 重新抓法規，輸出到 web/data/
```

**部署到 GitHub Pages**：把專案推到 GitHub，到 Settings → Pages → Source 選「GitHub Actions」，
`.github/workflows/pages.yml` 會在每次推到 `main` 時發佈 `web/`。

> 把自己的 API key 輸入任何網頁都有風險：請只在你信任的網址（你自己部署的、或審過原始碼的）使用，
> 並在 Anthropic Console 為這組 key 設定用量上限。

## 地區與版本

- **地區**：目前自治條例只收錄**苗栗縣**（苗栗縣建築管理自治條例，來源：苗栗縣政府法規系統）。
  選其他縣市仍可使用，只是只有全國法規，助理會提醒你地方規定沒載入。
- **版本**：全國法規來自[全國法規資料庫開放資料](https://law.moj.gov.tw/)，每次 `bca update` 會存成新快照，
  舊版保留在 `laws/<代碼>/<修正日>.json`。資料庫只提供現行版，所以舊版只能從你開始更新之後累積。

### 新增地區

1. 在 `bca/registry.py` 的 `LOCAL` 加入該縣市的法規（id、名稱、網址、`source`）。
2. 若該縣市的法規網站格式不同，在 `bca/fetch.py` 加一個 `parse_<縣市>()`，並讓 `fetch_local` 依 `source` 分派（目前只有苗栗的 parser）。
3. 在 `tests/test_core.py` 加一個用真實頁面片段的解析測試，再開 PR。

## 評測

`bca eval --judge` 跑 9 題（含跨法規、地方法規的題目）：檢查正確條文有沒有被找到，並請 Claude 對照參考答案批改。
`bca/eval_questions.json` 的參考答案都對照過條文；新增題目時請照做。

目前結果（2026-11-06）：**檢索 9/9**；答案批改約 **7–8/9**，每次跑會差 1 題左右——模型回答與批改措辭都有隨機性
（例如同一題有時被批「結論不夠明確」），所以請看趨勢，不要把單次結果當定論。

`python3 -m unittest discover -s tests`（Python）與 `node --test web/test/search.test.mjs`（網頁搜尋）跑不用網路、不用 AI 的單元測試。

## 已知限制

- **附表與附圖沒有載入**。有些條文的內容在附表／附圖（例如使用類組附表、部分圖例），資料庫只提供文字條文。
  助理遇到這類情況應該說明；請以官方附件為準。
- **只有條文，沒有函釋、判例、都市計畫書的土地使用分區管制**（建蔽率、容積率、退縮等因地而異）。
- **自治條例只有苗栗縣**；其他縣市要自己加（見上）。
- 搜尋用關鍵字（BM25），不是語意向量搜尋；口語詞彙若與法條用字差太多可能找不到，可在 `bca/assistant.py` 的 `GLOSSARY` 補同義詞。
- 一題要 20–60 秒（呼叫兩次 Claude）。
