# 香港招標項目處理 Agent（tender-pipeline）

本資料夾是「香港招標項目處理 agent」的工作空間。Agent 由 Hermes 驅動，每日自動執行以下流程：

1. **發現** — 從 Conneciz 公開 API（無須帳號登入）取得新招標項目
2. **核實** — 以搜尋引擎尋找官方招標通告及詳情（截止日期、文件連結等）
3. **取得文件** — 官方頁直接下載／官方平台需登入（用戶自行輸入帳號密碼）／線下索取（生成任務卡，用戶取回後續行）
4. **消化** — 生成 `01_digest.md`（項目摘要）與 `02_compliance.md`（規範／合規清單）

## Agent 架構

| 部件 | 技術 | 說明 |
|---|---|---|
| Agent 大腦 | Hermes（現成，已安裝） | 判斷新舊項目、搜索官方頁、消化文件、撰寫摘要 |
| 排程 | Hermes cron | 每日定時自動執行（時段待定） |
| 發現腳本 | Python 3 標準庫（無第三方依賴） | `scripts/discover.py` |
| 狀態儲存 | `pipeline_state.json` | 已見記錄、增量 watermark |
| 每個招標 | `dossiers/<編號>_<名稱>/` | `state.json`、`docs/`、`01_digest.md`、`02_compliance.md` |

```
每日 cron 叫醒 Hermes
      │
      ▼
① 發現：discover.py → Conneciz 公開 API（零登入）
      │ 新項目？
      ▼
② 核實：Hermes 用 web_search 搵官方招標通告頁
      ▼
③ 取得文件：直連下載 / 用戶登入官方平台 / 線下索取（用戶交接）
      ▼
④ 消化：Hermes 讀 PDF → 寫 01_digest.md + 02_compliance.md
      ▼
向用戶報告總結 + 待辦（punch list）
```

## 檔案結構

```
tender-pipeline/
├── README.md                  # 本文件
├── .hermes/plans/             # 實施計劃
├── scripts/discover.py        # 第一步：Conneciz 公開 API 發現腳本
├── pipeline_state.json        # 狀態（自動生成）
└── dossiers/                  # 每個招標一個資料夾（自動生成）
    └── <TenderNo>_<short-name>/
        ├── state.json         # 該招標嘅處理狀態
        ├── docs/              # 招標文件（下載或用戶放入）
        ├── 01_digest.md       # 項目摘要
        └── 02_compliance.md   # 規範／合規清單
```

## 用法

無任何第三方依賴，直接用系統 Python 3 執行。

### 旗標一覽

| 旗標 | 作用 | 預設 |
|---|---|---|
| `--baseline` | 重設基線：把過去 N 日記錄標為「已見」，不報新項目 | 關閉（首次執行、無 `watermark_ts` 時會自動進入基線模式） |
| `--since <ts>` | 手動指定起始時間戳（ISO 8601 UTC），覆蓋預設起始點 | 增量用 `watermark_ts`；基線用 `now - lookback_days` |
| `--lookback-days <N>` | 基線回望日數（只在 `--baseline` 生效） | `7` |

### 例子

**① 首次設定基線（預設回望 7 日）**

```bash
python3 scripts/discover.py --baseline
```

把最近 7 日內改動過嘅記錄標為「已見」，之後唔會當新項目報。輸出 `"new": []`。

**② 基線但回望 30 日**（想一次過涵蓋更長歷史）

```bash
python3 scripts/discover.py --baseline --lookback-days 30
```

**③ 基線但由指定時間起計**（`--since` 會覆蓋 `--lookback-days`）

```bash
python3 scripts/discover.py --baseline --since 2026-08-01T00:00:00.000Z
```

**④ 日常增量檢查（無旗標）**

```bash
python3 scripts/discover.py
```

以 `watermark_ts` 為起點，只報「新」或「改動過」嘅項目，並推前 watermark。

**⑤ 測試／手動 watermark（唔會推前已存 `watermark_ts`）**

```bash
python3 scripts/discover.py --since 2026-08-20T00:00:00.000Z
```

模擬「如果 watermark 係 8 月 20 日」會見到咩新項目，用嚟測試或排查。

> 注意：
> - `--since` 嘅時間戳要用 ISO 8601 UTC，例如 `2026-08-20T00:00:00.000Z`。
> - `--since` 只係唔推前 watermark；若佢拉到新記錄，仍會寫入 `tenders_seen`（唔係純唯讀 dry-run）。
> - 對 Conneciz 只作只讀查詢（公開 API，無登入），每頁間隔 0.3 秒。

## 狀態機（每個招標）

```
discovered → searching → official_found → docs_downloading → docs_ready → digested → done
                │           ├─ closed_skip（官方頁顯示已截止）
                └─ not_found └─ needs_login / offline_only → waiting_user（用戶交接）
```

## 依賴關係

- 舊項目 `~/Desktop/tender-agent/`（discovery app）保留作參考及 Web UI，本 pipeline 不依賴它。
- 招標投標撰寫階段（Step 5+）將使用 `tender-writing` skill 及 `~/Desktop/tender/company_library/`。
