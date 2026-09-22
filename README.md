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
# Portal 容器以 uid 1000 執行，store 須可寫入
sudo chown -R 1000:1000 store
docker compose up -d --build
```

| 網址 | 用途 |
|------|------|
| http://localhost:8501/login | Portal 登入 |
| http://localhost:8501/help | **使用手冊**（登入後側欄也可進入） |

檢查：`docker compose ps` · `curl -s http://localhost:8501/health`

首次登入以 `.env` 帳密；成功後須立即變更密碼。側欄 Agent 狀態為 **Online** 表示 Portal 可連 Agent。

> **`store/` 權限：** Compose 將主機 `./store` 掛載至容器 `/data/store`。Portal 以 **uid 1000** 讀寫此目錄（含 `portal_auth.db`、備份快照、索引）。新安裝或 clone 後請先 `chown -R 1000:1000 store`，否則可能無法登入或 Portal 異常。

---

## 更新

```bash
# 1. 備份資料
tar -czf store-backup-$(date +%Y%m%d).tar.gz store/

# 2. 拉程式並重建
git pull origin main
docker compose build --no-cache portal
docker compose up -d --build

# 3. 修正 store 擁有者（自舊版升級時必做；若已是 1000:1000 可略過）
sudo chown -R 1000:1000 store

# 4. 確認
docker compose ps
curl -s http://localhost:8501/health
```

自舊版升級時，若 `./store` 仍為 **root** 擁有，Portal 可能登入失敗或容器反覆重啟；執行上述 `chown` 後再 `docker compose up -d portal` 即可。

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
