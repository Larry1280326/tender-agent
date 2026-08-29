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

```bash
# 首次：設定基線（視過去 7 日記錄為「已見」，不會報新項目）
python3 scripts/discover.py --baseline

# 日常：增量檢查（只報新項目，輸出 JSON）
python3 scripts/discover.py
```

- 無任何依賴，直接以系統 Python 3 執行。
- 對 Conneciz 只作只讀查詢（公開 API，無登入），每頁間隔 0.3 秒。

## 狀態機（每個招標）

```
discovered → searching → official_found → docs_downloading → docs_ready → digested → done
                │           ├─ closed_skip（官方頁顯示已截止）
                └─ not_found └─ needs_login / offline_only → waiting_user（用戶交接）
```

## 依賴關係

- 舊項目 `~/Desktop/tender-agent/`（discovery app）保留作參考及 Web UI，本 pipeline 不依賴它。
- 招標投標撰寫階段（Step 5+）將使用 `tender-writing` skill 及 `~/Desktop/tender/company_library/`。
