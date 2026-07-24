# NetdriverBackup — NCCM v3

企業網路設備組態備份與庫存：**FastAPI Portal** + **NetDriver Agent**（Docker）。備份寫入 **`store/`**，索引為 **`store/index.db`**。

**GitHub：** https://github.com/moltmotl5-bot/NetdriveBackup

---

## 快速開始

```bash
git clone https://github.com/moltmotl5-bot/NetdriveBackup.git
cd NetdriveBackup
cp .env.example .env    # 設定 NCCM_ADMIN_PASS（≥12 字元）
chmod 600 .env
mkdir -p store
docker compose up -d --build
```

| 網址 | 用途 |
|------|------|
| http://localhost:8501/login | Portal 登入 |
| http://localhost:8501/help | **使用手冊**（登入後側欄也可進入） |
| http://localhost:8000/docs | Agent API（除錯） |

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
| **netdriver-agent** | SSH 連線與廠牌 plugin |
| **store/** | 持久化 volume（務必備份） |

---

## 設備 CSV

必填：**`Site,IP,Vendor,Port`**

| Vendor | 說明 |
|--------|------|
| `cisco` | IOS / NX-OS（不含 WLC） |
| `huawei` | CE 系列（不含 WLC） |
| `fortinet` | FortiGate |

範例見 `DEMO-v3.csv`。SSH 帳密在 Web 表單輸入，不寫入 `.env`。

---

## Web 功能

1. **批次備份** — CSV + SSH，SSE 即時 log  
2. **設備總表** — 版控、Config Diff、快照保留（admin/operator）  
3. **CDP/LLDP 鄰居** · **Interface Map**  
4. **排程備份** — CSV 上傳 → Agent 探測 → 以**日**為週期自動備份  

| 能力 | admin | operator | viewer |
|------|-------|----------|--------|
| 批次備份／索引／retention | ✓ | ✓ | ✗ |
| 排程（操作） | ✓ | ✓ | ✗ |
| 排程（唯讀）／總表／鄰居／介面 | ✓ | ✓ | ✓ |
| 使用者／API Token／審計 | ✓ | ✗ | ✗ |

首次 bootstrap 登入後須變更密碼。API 以 admin 建立 Token，標頭 `X-API-Key`。

---

## 環境變數（常用）

| 變數 | 說明 |
|------|------|
| `NCCM_ADMIN_USER` / `NCCM_ADMIN_PASS` | Web 登入 |
| `NCCM_NETDRIVER_URL` | Portal → Agent（Compose 預設 `http://netdriver-agent:8000`） |
| `NCCM_STORE_DIR` | 備份根目錄（容器內 `/data/store` → `./store`） |

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
pip install -r requirements-dev.txt
pytest
```

---

## 疑難排解

| 現象 | 處理 |
|------|------|
| Agent 離線 | `docker compose logs netdriver-agent` |
| 備份失敗 | 確認 Agent 容器可 SSH 至設備；看 Portal SSE log |
| Agent unhealthy | `docker compose down -v && docker compose up -d --build` |
| 庫存不對 | Web「重建索引」；Stack/HA 異常時重新備份 |

---

MIT License
