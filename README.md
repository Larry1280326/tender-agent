# 招標助理（Tender Assistant）

一個由 **LangGraph agent** 驅動嘅香港招標助理：用戶喺 web UI 建立「專案」（一個專案 = 一個招標項目），
每次新專案 agent 都即時用 Conneciz 讀取香港**非政府**招標列表俾用戶揀，揀完就綁定到該專案；
之後用 Serper 搜尋官方來源、用 Jina Reader 讀頁，仲可以做核實、下載文件、生成摘要。

- **大腦**：LangGraph `create_react_agent` + DeepSeek（`langchain-openai.ChatOpenAI`）
- **工具（8 個）**：`list_tenders`、`select_tender`、`verify_tender`、`download_docs`、`digest_tender`、`search_web`、`read_page`、`send_email`
- **記憶**：`AsyncSqliteSaver`（`langgraph-checkpoint-sqlite`）持久化對話，重啟唔會失憶
- **界面**：Next.js 14 左側 session 列表 + 右側聊天

## 檔案結構

```
tender-pipeline/
├── backend/
│   ├── .env / .env.example   # API keys（.env 已 gitignore）
│   ├── pyproject.toml        # uv 專案，deps 含 langgraph-checkpoint-sqlite
│   └── app/
│       ├── main.py           # FastAPI + CORS + routers（lifespan 初始化 agent）
│       ├── config.py         # env + 設定（DeepSeek / Serper / Jina / Gmail / DATA_DIR）
│       ├── llm.py            # build_model() → DeepSeek ChatOpenAI
│       ├── classify.py       # 香港 + 政府／非政府 hybrid 分類（關鍵字 + Jina + LLM）
│       ├── sessions.py       # session 元資料（backend/data/sessions.json）
│       ├── store.py          # 所選項目狀態（讀寫 tender_state.json）+ dossiers
│       ├── nodes.py          # 核實／下載／消化 node 邏輯
│       ├── services/         # Conneciz 列表 + Serper + Jina Reader + tender_state/共用工具
│       ├── agent/
│       │   ├── agent.py      # react agent + AsyncSqliteSaver + system prompt
│       │   └── tools.py      # 8 個工具（含 send_email），discover/list 預設套非政府過濾
│       └── api/              # chat（SSE 串流）／sessions／tenders
└── frontend/
    ├── app/page.tsx          # 左 session 列表 + 右聊天 兩欄
    ├── components/Sidebar.tsx  # session 列表 +「＋ 新專案」
    ├── components/Chat.tsx     # 串流渲染 +「選取項目」panel
    └── lib/api.ts            # 後端 API 封裝 + 型別
```

## 事前準備

### 1. 後端 API keys

複製 `backend/.env.example` 做 `backend/.env` 並填入：

```bash
DEEPSEEK_API_KEY=…          # DeepSeek
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
SERPER_API_KEY=…            # Serper 搜尋
JINA_API_KEY=…              # Jina Reader 讀頁
GMAIL_USER=…                # Gmail 寄信（可選，只用 send_email 時需要）
GMAIL_APP_PASSWORD=…        # Google App Password（16 位字元）
```

> `TENDER_DATA_DIR`（可選）指定資料隔離目錄，預設 `backend/data`。所有狀態
> （`tender_state.json`、`sessions.json`、`checkpoints.sqlite`、`dossiers/`）都落喺呢度。

### 2. 啟動後端

```bash
cd backend
uv sync                          # 首次
uv run uvicorn app.main:app --reload
```

啟動後 `GET /sessions`、`POST /sessions`、`GET /tenders?scope=non_gov`、`POST /chat/stream` 可用。

### 3. 啟動前端

```bash
cd frontend
npm install                      # 首次
npm run dev
```

開 `http://localhost:3000`（後端預設 `http://localhost:8000`，可經 `NEXT_PUBLIC_API_URL` 覆蓋）。

## 用法

1. 按「**＋ 新專案**」建立新 session，agent 會自動即時讀取 Conneciz，列出所有**香港非政府**招標項目（連 tender_id）。
2. 喺對話中揀項目（例如「選第2個」），agent 會 call `select_tender` 綁定並寫入 `tender_state.json`，
   session 會改名做嗰個招標標題；之後所有核實／下載／摘要都預設對住佢。
3. 直接喺聊天框問 agent，例如「核實呢個項目」「下載文件」「生成摘要」。

## 香港非政府分類

Conneciz 公開 API 冇招標方欄位，所以用 **hybrid** 方式分「香港非政府」：

1. **關鍵字預篩**：喺標題／slug 排除政府部門（署／處／局／政府／部門／Department／Government 等），
   但**刻意保留**法定機構（醫管局、大學）同私營機構／NGO —— 呢啲都算「非政府」。
2. **邊界／頭部結果**：用 Jina Reader 讀詳情頁 + LLM 抽招標方，再重新分類。

## 寄電郵（send_email）

agent 可以透過 Gmail 信箱代你寄電郵。因為寄信係不可逆嘅對外動作，工具會先**暫停並請你確認**收件人／主旨／內容，你喺聊天介面見到 inline 核准卡、撳「確認發送」先真正寄出。

### 設定

喺 `backend/.env` 加（需喺 Google 帳戶開「應用程式密碼」App Password，16 位字元；2FA 要先開）：

```bash
GMAIL_USER=your@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
```

### 流程

1. agent 決定寄信，call `send_email(to, subject, body)`，並用 LangGraph `interrupt()` 暫停（未寄出）。
2. 後端經 SSE 出 `approval_required` 事件，前端喺對話中顯示 inline 核准卡（收件人／主旨／內容）。
3. 你撳「確認發送」→ `POST /chat/approve` 以 `Command(resume={"approved": true})` 繼續，真正寄出；撳「取消」就唔寄。

### 注意：VPN／代理（TUN 模式）會截走 SMTP

若開咗 Clash 類代理（例如 FlClash）嘅 **TUN 模式**，佢會攔截所有 TCP，令 Gmail SMTP
（`smtp.gmail.com:587`）連線超時／被斷。解決方法二選一：

- 關閉 TUN 模式（改用「系統代理」即可；`smtplib` 唔經 HTTP 代理，會直連）。
- 或喺規則加 DIRECT：

```yaml
rules:
  - DOMAIN-SUFFIX,smtp.gmail.com,DIRECT
  - DOMAIN-SUFFIX,smtp.googlemail.com,DIRECT
  - DST-PORT,587,DIRECT
  - DST-PORT,465,DIRECT
```

（fake-ip 模式可順便將 `smtp.gmail.com` 加入 `dns.fake-ip-filter`。）

## API 摘要

| Method | Path | 作用 |
|---|---|---|
| `GET` | `/sessions` | 列出所有專案 |
| `POST` | `/sessions` | 建立新專案 |
| `PATCH` | `/sessions/{id}` | 改名／綁定招標（`title` + `tender_id`） |
| `GET` | `/sessions/{id}/messages` | 重建對話歷史（由 checkpoint 讀返） |
| `GET` | `/tenders?scope=non_gov` | 已選取嘅香港非政府招標列表 |
| `POST` | `/chat/stream` | SSE 串流 agent 回覆（`text`／`tool_start`／`tool_end`／`approval_required`／`done`／`error` 事件） |
| `POST` | `/chat/approve` | 核准／取消寄電郵（`approved`），繼續被 `interrupt` 暫停嘅 agent |
