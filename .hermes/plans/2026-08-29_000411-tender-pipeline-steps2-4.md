# 招標項目處理 Pipeline（Step 2–4）實施計劃

> **For Hermes:** 逐個 Phase 執行,每個 Phase 用真實 tool output 驗證通過先落下一步。

**Goal:** 喺現有 discovery 層（`~/Desktop/tender-agent`,已建成）之上,建立一條 agent 驅動嘅處理 pipeline:**Conneciz 公開 API（無須帳號登入）發現新招標** → 搜尋引擎搵官方資料 → 取得招標文件（自動下載／用戶登入交接／線下索取）→ 消化生成 `01_digest.md` + `02_compliance.md`,為 Step 5+（投標撰寫）做好準備。**Conneciz 純粹係項目發現入口,項目詳情一律經搜尋引擎向官方來源核實。**

**Architecture:** 混合式。Discovery（Step 1）用 Conneciz **公開 Data API（無須帳號登入）** 喺現有 standalone app 入面做 incremental sync;Step 2–4 係 **Hermes-native agent pipeline**——cron job 定期跑 sync,agent 用 `web_search` 搵官方頁、以 Playwright 持久 profile 處理**官方文件網站**嘅登入門檻（Conneciz 永不登入）、用 LLM 生成消化文件,用戶留喺 loop 入面處理登入／線下取文件。狀態以 per-dossier `state.json` 追蹤。

**Tech Stack:** 現有 `tender-agent` app（Python 3.11 + uv + httpx + Playwright + SQLite/FTS5）;Hermes cron + skills（`tender-writing`、`web-scraping-recon`、`ocr-and-documents`）;PDF 解析用 `read_file` 原生抽取 + pymupdf/OCR fallback。

---

## 背景與現狀（2026-08-28 核實）

**Step 1（發現）已建成**,git 進度至 Phase 3:

- Conneciz 公開 Data API（watermark 分頁）+ active-list harvest（Azure Search XHR replay + 登入 session,持久 profile `data/browser_profile/`）。
- PCMS2 純 REST harvest（空關鍵字 screens API = 全部 44 個 GLD 現行招標）。
- SQLite + FTS5、跨源 dedup（44/44 配對）、CLI（`sync all` / `list --q … --json`）、FastAPI Web UI。
- **用戶決策（2026-08-29):Conneciz 無須帳號登入,純做項目發現。** 現有嘅 Conneciz login-based active harvest（`scripts/conneciz_login.py`、`data/browser_profile/`)本 pipeline 唔會再用,保留喺 repo 但唔呼叫;項目詳情（截止日期、文件等）一律經搜尋引擎搵官方來源。
- 已知缺口（本計劃已繞過）:login-based active harvest 只覆蓋 ~180/236——公開 API 已含全部 ~22k 記錄（包括最新),唔受影響;category code→label 映射未捕獲（可選,唔阻塞）。

**本計劃範圍 = Step 2–4**（官方搜尋 → 文件取得 → 消化)。Step 5+（投標撰寫）另開計劃,喺 Step 4 驗證後再寫。

---

## 架構決策

| 部分 | 放邊 | 原因 |
|---|---|---|
| Discovery sync + DB | 現有 app,只跑 `sync conneciz --no-active`（公開 API,零登入) | 已建成、已驗證;login harvest 棄用 |
| Step 2 官方搜尋 | Hermes agent（`web_search`) | 需要 LLM 判斷官方頁、跨搜尋引擎 |
| Step 3 文件下載 | 混合:直連下載用 script;官方文件網站如需登入先開 Playwright 可見瀏覽器（持久 profile 模式) | 登入只針對官方文件網站,**Conneciz 永不登入**;用戶自己入密碼,agent 永不經手憑證 |
| Step 4 消化文件 | Hermes agent（LLM 生成 md) | 需理解規格文本,輸出書面中文 |
| 排程 + 用戶交接 | Hermes cron（`attach_to_session`) | cron 跑得通嘅自己做,要人出手嘅發訊息等用戶回覆續行 |

**替代方案（已否決):** 全部搬入 standalone app（自帶 LLM key + Web UI 交接）——重複實現 Hermes 已有能力,且用戶交接體驗差過直接喺 chat 入面處理。

---

## 流程狀態機（每個招標一個 dossier）

```
discovered ──▶ searching ──▶ official_found ──▶ docs_downloading ──▶ docs_ready ──▶ digested ──▶ done (交 Step 5+)
   ▲              │                │                   │                 ▲
   │              └─ not_found ────┘                   ├─ needs_login ──┼─▶ waiting_user
 baseline 前嘅舊記錄       （換查詢組重試,        │  └─ offline_only ┘  （用戶登入／取文件後 resume）
 唔當新項目              再唔得問用戶）          └─ closed_skip（官方頁顯示已截止 → 記錄原因,唔下載）
```

- `needs_login` / `offline_only` → cron 發 punch list 俾用戶;用戶喺 chat 回覆或將文件放入 dossier → resume。
- 每個 run 最多處理 3–5 個新招標（cap),有 `pipeline_runs` 記錄每次執行。

## 資料夾與狀態設計

```
~/Desktop/tender/                          # 沿用 tender-writing skill 嘅 dossier 根目錄
├── pipeline_state.json                    # 全局: last_sync_at、處理中 dossier、punch list
└── <TenderNo>_<short-name>/               # 每個招標一個 dossier
    ├── state.json                         # 狀態機 + official_url + 每個文件來源記錄
    ├── docs/                              # 下載／用戶放入嘅招標文件 (PDF)
    ├── 01_digest.md                       # 項目摘要（書面中文）
    └── 02_compliance.md                   # 規範／合規清單（書面中文）
```

命名:`01_digest.md` / `02_compliance.md` 按用戶指示;內容結構參考 `tender-writing` skill 嘅 Step 2–3（`01_spec_digest.md` / `02_compliance_checklist.md` 模板),確保 Step 5+ 可以無縫接上現有投標 workflow。

---

## Phase A — Pipeline 骨架

### Task A1: 核實 sync 指令輸出
**Files:** 無改動。
- 記錄 runbook:`cd ~/Desktop/tender-agent && uv run tender-agent sync conneciz --no-active`(公開 API incremental,零登入;PCMS2 可選加跑 `sync pcms2`,同樣零登入)。
**Verify:** 手動跑一次,輸出正常、`scrape_runs` 有新記錄;確認全程無需任何登入 session。

### Task A2: `pipeline_state.json` + dossier 創建 script
**Files:** Create `~/Desktop/tender-agent/scripts/pipeline.py`(獨立 script,唔入 app package 以免影響現有 UI)。
- `pipeline.py new-tenders`:`tender-agent list --json` 比對 `pipeline_state.json` 已有 dossier 清單 → 輸出新招標列表（source、ref、title_en/zh、closing_at、url)。**基線機制:** 首次 run 記錄 `baseline_ts`,之前嘅歷史記錄一律唔當新項目;之後只處理 `first_seen > last_processed_ts` 嘅行。
- `pipeline.py dossier-create <id>`:按 `<TenderNo>_<short-name>` 建立 dossier + 空 `state.json`(status=discovered, 記錄 tender id、ref、title、source、url、date)。
- `pipeline.py status`:列出所有 dossier 狀態 + 有待辦（waiting_user)項目。
**Verify:** 首次 run 唔會將 ~22k 歷史記錄當新項目（基線生效);dossier 名無非法字符;重複執行唔會重複建 dossier。

### Task A3: 試跑一個 end-to-end 例子（天文台招標)
用 screenshot 嗰個天文台項目做 seed,手動行通 Step 2→3→4 一次,校準每個 step 嘅 prompt 同輸出格式。
**Verify:** 一個 dossier 完整產生 `01_digest.md` + `02_compliance.md`,用戶確認格式。

---

## Phase B — Step 2:官方資料搜尋（agent 化)

### Task B1: 搜尋策略 + 官方域評分
- 每個新招標,agent 用 `web_search` 跑 2–3 組查詢:`"<Tender_No>" 招標`、`<Subject_EN>`、`<招標方> 招標公告`(用戶例子:天文台 → HKO 官網招標通告頁)。
- 結果評分:優先 `*.gov.hk`、`*.edu.hk`、招標方自己嘅域名;其次新聞／聚合站(僅作參考)。
- 記錄落 `state.json`:`official_url`、`official_title`、`search_queries`、`found_at`。

### Task B2: 官方頁抽取
- 攞到官方頁後,抽取:招標編號、截止日期（同 DB 對照)、聯絡人／查詢渠道、**招標文件下載連結清單**(PDF 連結 + 任何「下載招標文件」按鈕)。
- 官方頁可能需要 JS 渲染 → 用 Playwright 或 `browser_navigate` 攞最終 DOM。
**Verify:** 天文台例子:搵到 HKO 官方通告頁,抽取到 PDF 連結。

### Task B3: Fallback — 搵唔到官方頁
- 官方搜尋失敗 → 換查詢組重試（加招標方全名／中文名／政府部門名)。
- 再搵唔到 → `state.json` 標 `not_found`,punch list 通知用戶俾官方 URL。**唔用 Conneciz 詳情頁頂替**（按用戶決策,Conneciz 只做發現)。
**Verify:** 一個查詢組失敗後第二組成功;一個真係搵唔到嘅 case 正確落入 punch list。

---

## Phase C — Step 3:文件取得（三通道)

### Task C1: 直接下載（無登入)
- 官方頁有直接 PDF 連結 → `httpx` stream 下載入 `dossier/docs/`(1 req/s,UA 設定,大小上限 100MB)。
- 記錄每個文件:來源 URL、文件名、大小、SHA1、下載時間 → `state.json.files[]`。
**Verify:** 天文台 PDF 成功落碟、可以開。

### Task C2: 需登入 → 用戶交接（可見瀏覽器,只限官方文件網站)
- **Conneciz 永不登入。** 登入 handoff 只存在於官方文件網站（例:政府部門 e-tender 平台要求登入先下載到招標文件)。
- 沿用現有 login script 嘅持久 profile 做法（`scripts/conneciz_login.py` 嘅技術模式,但針對官方平台):agent 開 **可見** Playwright 瀏覽器（持久 profile),**用戶自己輸入帳號密碼**,登入後 session 保存。
- 之後 agent 用同一 profile headless 下載文件。
- 每個平台一個 adapter(PCMS2 供應商入口、部門 e-tender 平台等),按需逐個起,唔好一嚟就做通用版。
- Session 過期 watchdog:下載時偵測 login redirect → `state.json` 標 `needs_login`,通知用戶再登入。
- **安全原則:agent 永不會要求或代用戶輸入任何密碼。**
**Verify:** 一個需登入平台完成登入 + 下載;刪 cookies 後 watchog 正確觸發。

### Task C3: 線下索取 → 用戶交接
- 官方資料顯示要打電話／親身／郵寄索取 → agent 生成 `dossier/03_fetch_task.md`（取文件任務卡:聯絡人、電話、地址、所需文件清單、注意事項、建議完成日期)。
- 通知用戶;用戶取完後將文件放入 `dossier/docs/`,下次 run（或用戶喺 chat 講聲)自動偵測並繼續。
**Verify:** 任務卡資訊完整、可照住執行。

---

## Phase D — Step 4:消化文件

### Task D1: 文本抽取
- `read_file` 原生抽取 PDF 文本 → `dossier/00_spec_extracted.md`。
- 掃描件／抽取失敗 → pymupdf → OCR fallback（`ocr-and-documents` skill)。
**Verify:** 抽取文本包含招標編號、截止日期、條件等關鍵段。

### Task D2: 生成 `01_digest.md`（書面中文)
內容(跟 tender-writing Step 2):
- 買方、招標編號、項目名稱、預算上限及幣種
- 關鍵日期:截止、簡報會、開標、判標
- 工作範圍摘要（保留招標文件原文用詞)
- 提交機制:e-tendering 平台、信封制度（雙信封?)、上載規則
- 評審準則及完整評分表
- 聯絡人／查詢渠道、文件來源出處（每個資料點標明來源)
**Verify:** 與原 PDF 逐點對照抽查,無幻覺資料;所有日期準確。

### Task D3: 生成 `02_compliance.md`
內容(跟 tender-writing Step 3 模板):
- 每項 [Mandatory] 條款(附規格出處)
- 取消資格條件(例:雙信封技術卷出現價格 = DQ)
- 必須提交嘅表格／附件及其簽署／蓋章要求
- 截止時間,包括逾期補交窗口(如有)
**Verify:** grep 原文件確認每條 Mandatory 都有對應出處;同 `01_digest.md` 日期一致。

---

## Phase E — Cron 編排 + 用戶交接

### Task E1: cron job `tender-pipeline`
- 每日 08:00 HKT,`attach_to_session=true`,deliver 返 origin chat;掛 `tender-writing` + `web-scraping-recon` skills。
- 每次 run 做:`sync conneciz --no-active`(可選加 `sync pcms2`)→ `new-tenders`(cap 5)→ 每個新招標建 dossier → 盡力跑 Step 2 + Step 3 直連下載 → docs_ready 嘅跑 Step 4 → 出總結訊息:發現咗咩、邊個 dossier 完成、邊個要用戶出手(punch list)。
- 冇新招標 → 靜默或一句「今日無新招標」。
**Verify:** 手動 trigger 一次,訊息格式、punch list 正確。

### Task E2: Resume 流程（用戶回覆續行)
- 用戶喺 chat 回覆「登入咗」／「文件放咗入 folder」→ agent 讀 `state.json` 續行(登入平台 → 下載;docs 就緒 → Step 4)。
- 用戶直接放文件入 `dossier/docs/` → 下次 cron run 自動偵測續行。
**Verify:** 兩種 resume 路徑各試一次。

### Task E3: 失敗可見性
- `pipeline_runs` 記錄每次執行(開始／結束、處理數、失敗原因);任何失敗都喺總結訊息報告,唔會靜默。
**Verify:** 人為製造一個下載失敗,確認訊息有報。

---

## Step 5+ 展望（另開計劃,Step 4 驗證後先寫)

預計:投標／唔投標決策（按 02_compliance + 公司能力)→ `03_proposal_outline.md`(marking scheme 配分)→ 用 `tender-writing` skill + `company_library` 起稿 → 包裝／提交（`docx`、`pdf` skills)。此階段完成後,agent 變成真正「發現 → 判斷 → 寫標書 → 提標」嘅閉環。

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| 登入平台五花八門(每個 portal 唔同) | 中 | 按需逐個起 adapter,唔做通用版;官方頁直連下載優先 |
| 官網 PDF 係掃描件,OCR 質素差 | 中 | pymupdf→OCR fallback;digest 標註「未能完全抽取」段 |
| web_search 搵唔到官方頁 | 中 | 換查詢組重試;仍搵唔到 → punch list 提用戶俾官方 URL |
| 新招標量大(Conneciz active ~236) | 中 | 每 run cap 5 個;Step 2 起就按「相關性／類別」過濾(見 open questions) |
| Playwright 可見瀏覽器打擾用戶 | 低 | 只喺用戶回覆同意後先開;headless 優先 |
| Conneciz 公開 API 冇截止日期字段 | 中 | 截止日期由 Step 2 官方頁核實;公開 API 純做發現（新記錄以 Modified Date 判斷) |
| 公開 API 嘅「新記錄」唔一定係新招標（舊記錄被編輯會浮返上嚟) | 低 | Step 2 官方頁核實截止日期,已截止 → `closed_skip`,唔下載文件 |

## Remaining open questions

1. **處理範圍** — 所有新招標都消化,定係只處理你業務相關嘅類別／關鍵字?(建議:先加一個 keyword／類別白名單,否則每日幾個 digest 會好快氾濫。你嘅公司做邊類?)
2. **通知渠道** — cron 總結訊息發返而家呢個 chat,定係同步埋 Telegram(@dontknowwhatnametomake)?
3. **Dossier 命名** — `01_digest.md` / `02_compliance.md` 照你講嘅;但 `tender-writing` skill 慣例係 `01_spec_digest.md` / `02_compliance_checklist.md`,兩套並存會亂。我建議統一用你嗰套(plan 已假設),OK?
4. **處理時段** — 每日 08:00 HKT 跑 sync + 消化,啱唔啱?定係你想一日兩次(08:00 / 20:00)?

## Acceptance criteria (definition of done)

- 每日 cron 自動 sync Conneciz 公開 API（零登入);新招標自動建 dossier。
- 每個新招標:官方頁搵到並記錄（搵唔到則入 punch list);文件經三通道之一落入 `docs/`。
- 需要用戶出手嘅項目,用戶收到 punch list;登入／放文件後可續行,唔會卡死或重複處理。
- docs 就緒嘅 dossier 自動生成 `01_digest.md` + `02_compliance.md`(書面中文、有出處、日期準確)。
- 天文台例子 end-to-end 行通,用戶確認輸出格式。
