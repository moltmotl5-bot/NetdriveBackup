# NetdriverBackup — NCCM v3

企業網路設備組態備份與庫存：**FastAPI Portal** + **NetDriver Agent**（Docker）。備份寫入 **`store/`**，索引為 **`store/index.db`**。

**GitHub：** https://github.com/moltmotl5-bot/NetdriveBackup

---

## 快速開始

```bash
git clone https://github.com/moltmotl5-bot/NetdriveBackup.git
cd NetdriveBackup
cp .env.example .env
python3 -c "import secrets; print('NCCM_AGENT_HMAC_SECRET=' + secrets.token_hex(32)); print('NCCM_SESSION_SECRET=' + secrets.token_hex(32))" >> .env
# 編輯 .env：設定 NCCM_ADMIN_PASS（≥12 字元）
chmod 600 .env
mkdir -p store
docker compose up -d --build
```

| 網址 | 用途 |
|------|------|
| http://localhost:8501/login | Portal 登入 |
| http://localhost:8501/help | **使用手冊**（登入後側欄也可進入） |

檢查：`docker compose ps` · `curl -s http://localhost:8501/health`

更新：`git pull && docker compose up -d --build`（重大變更前請備份 `./store`）

---

## 架構

```
瀏覽器 → nccm-portal (FastAPI) → netdriver-agent (SSH) → 網路設備
                ↓
            store/（快照 + SQLite 索引）
```

| 元件 | 說明 |
|------|------|
| **portal** | Web UI：備份、庫存、鄰居、介面、排程 |
| **netdriver-agent** | SSH 連線與廠牌 plugin（預設僅 Docker 內部網路可連） |
| **store/** | 持久化 volume（務必備份） |

---

## 設備 CSV

必填：**`Site,IP,Vendor,Port`**

| 欄位 | 規則 |
|------|------|
| **Site** | `A–Z` / `a–z` / `0–9` / `.` / `_` / `-` 開頭，最長 64；不可含 `/`、`\`、`..` |
| **IP** | 合法 IPv4 或 IPv6 |
| **Port** | 1–65535；預設允許 **22**、**2222**（可選 `NCCM_ALLOWED_SSH_PORTS=22,2222,830`） |
| **Vendor** | 見下表；WLC 不支援 |

| Vendor | 說明 |
|--------|------|
| `cisco` | IOS / NX-OS（不含 WLC） |
| `huawei` | CE 系列（不含 WLC） |
| `fortinet` | FortiGate |

範例見 `DEMO-v3.csv`。SSH 帳密在 Web 表單輸入，不寫入 `.env`。

---

## Web 功能

1. **批次備份** — CSV + SSH，SSE 即時 log  
2. **設備總表** — 版控、Config Diff、快照保留（admin/operator；保留需先 dry-run 再確認）  
3. **CDP/LLDP 鄰居** · **Interface Map**  
4. **排程備份** — CSV 上傳 → Agent 探測 → 以**日**為週期自動備份  

| 能力 | admin | operator | viewer |
|------|-------|----------|--------|
| 批次備份／索引／retention | ✓ | ✓ | ✗ |
| 排程（操作） | ✓ | ✓ | ✗ |
| 排程（唯讀）／總表／鄰居／介面 | ✓ | ✓ | ✓ |
| 使用者／API Token／審計 | ✓ | ✗ | ✗ |

首次以 `.env` bootstrap 登入後須變更密碼。REST API 以 admin 建立 Token，標頭 `X-API-Key`。

---

## 環境變數（常用）

| 變數 | 說明 |
|------|------|
| `NCCM_ADMIN_USER` / `NCCM_ADMIN_PASS` | Web 首次登入（bootstrap） |
| **`NCCM_AGENT_HMAC_SECRET`** | **必填** — Portal 與 Agent 通訊 |
| **`NCCM_SESSION_SECRET`** | **必填** — Web Session |
| `NCCM_NETDRIVER_URL` | Portal → Agent（Compose 預設 `http://netdriver-agent:8000`） |
| `NCCM_STORE_DIR` | 備份根目錄（容器內 `/data/store` → `./store`） |
| `NCCM_PORT` | Portal 對外埠（預設 8501） |
| `NCCM_ALLOWED_SSH_PORTS` | 可選 — CSV Port allowlist（預設 `22,2222`） |
| `NCCM_RETENTION_MAX_DELETE` | 可選 — 單次 retention 最多刪除筆數（預設 500） |

完整列表見 `.env.example`。

---

## 文件

| 文件 | 說明 |
|------|------|
| Portal **`/help`** | 使用手冊（安裝、操作、疑難排解） |
| [docs/NCCM-v3-spec.md](docs/NCCM-v3-spec.md) | 技術規格（開發者） |

---

## 測試

```bash
pip install -r requirements-v3.txt -r requirements-dev.txt
export NCCM_AGENT_HMAC_SECRET=test-hmac-secret
pytest
```

---

## 疑難排解

| 現象 | 處理 |
|------|------|
| `Set NCCM_AGENT_HMAC_SECRET in .env` | 在 `.env` 產生並設定，重啟 compose |
| `Set NCCM_SESSION_SECRET in .env` | 在 `.env` 產生並設定，重啟 compose |
| **CSRF validation failed** | 硬重新整理頁面；若經 HTTPS 反向代理請設 `NCCM_HTTPS=1`；本機 HTTP 請勿設 `NCCM_HTTPS=1` |
| 登入 **Internal Server Error** | `sudo chown -R 1000:1000 store` 後 `docker compose up -d --build` |
| Portal 反覆重啟 | `docker compose logs portal --tail 50`；常見為映像未重建或 `.env` 缺 `NCCM_SESSION_SECRET`／`NCCM_AGENT_HMAC_SECRET` |
| 使用手冊排版異常 | 重建 Portal 映像以取得 `/static/handbook.css` |
| Agent 離線 | `docker compose logs netdriver-agent`；確認 Agent 容器 healthy |
| 主機連不上 `:8000` | 預期行為；本機除錯 Agent 見下方 |
| CSV 匯入被拒 | 檢查 Site 字元、IP 格式、Port 是否在 allowlist |
| 備份失敗 | 確認 Agent 容器可 SSH 至設備；看 Portal SSE log |
| Agent unhealthy | `docker compose down -v && docker compose up -d --build` |
| 庫存不對 | Web「重建索引」；Stack/HA 異常時重新備份 |
| Retention 無法執行 | 須先按「預覽刪除」再按「確認執行清理」；token 5 分鐘有效 |

### Agent 本機除錯

僅在本機需要直接連 Agent API 時使用（綁定 `127.0.0.1`）：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
curl -s http://127.0.0.1:8000/health
```

---

MIT License
