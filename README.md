# NetdriverBackup — NCCM v3

企業網路設備組態備份與庫存平台：**FastAPI Web** + **NetDriver Agent（Docker）**。  
取代舊版 Streamlit / Netmiko 單體；**不支援 WLC**；備份資料寫入 **`store/`**，索引為 **`store/index.db`**。

**GitHub：** https://github.com/moltmotl5-bot/NetdriveBackup  
**完整圖文手冊：** [docs/Handbook.html](docs/Handbook.html)（瀏覽器開啟；含安裝、設定、各頁操作與維運）

---

## 架構

```
┌─────────────────┐     HTTP      ┌──────────────────────┐     SSH      ┌─────────────┐
│  瀏覽器 :8501    │ ────────────► │  nccm-portal         │            │  交換機 /    │
│  登入 + 四頁 UI  │               │  (FastAPI + HTMX)    │            │  防火牆 /    │
└─────────────────┘               └──────────┬───────────┘            │  路由器      │
                                             │ NCCM_NETDRIVER_URL      └──────▲──────┘
                                             ▼                            │
                                  ┌──────────────────────┐                │
                                  │  netdriver-agent     │ ───────────────┘
                                  │  (REST :8000)        │
                                  └──────────────────────┘
```

| 元件 | 說明 |
|------|------|
| **portal** | 批次備份（SSE 即時 log）、設備總表、CDP/LLDP、Interface Map |
| **netdriver-agent** | 對設備 SSH 連線、執行 CLI；映像由 `netdrive-agent/` 原始碼建置 |
| **store/** | 快照目錄 + SQLite 索引（請掛載持久化 volume） |

---

## 環境需求

| 項目 | 建議 |
|------|------|
| Docker | 24+（含 Compose v2） |
| 主機 | Linux / macOS；需能從 **Agent 容器** SSH 至設備管理網 |
| 瀏覽器 | 現代 Chromium / Safari / Firefox |

> **網路**：Agent 容器使用 bridge 網路時，必須能路由到設備管理 IP。若設備僅能從主機直連，可改 Agent 為 `network_mode: host`（見下方進階）。

---

## 快速部署（Docker Compose）

在專案根目錄：

```bash
git clone https://github.com/moltmotl5-bot/NetdriveBackup.git
cd NetdriveBackup

cp .env.example .env
# 編輯 .env：NCCM_ADMIN_PASS 至少 12 字元；REST API 請於 Portal「API Token」建立（見該頁手冊）
chmod 600 .env

mkdir -p store
docker compose up -d --build
```

若曾用舊版 Compose 且 Agent 顯示 **unhealthy**，請先清掉舊 volume 再啟動：

```bash
docker compose down -v
docker compose up -d --build
```

| URL | 用途 |
|-----|------|
| http://localhost:8501/login | NCCM Web（`.env` 帳密） |
| http://localhost:8000/docs | NetDriver Agent OpenAPI（除錯用） |

檢查狀態：

```bash
docker compose ps
docker compose logs -f portal
docker compose logs -f netdriver-agent
curl -s http://localhost:8501/health | python3 -m json.tool
```

停止：

```bash
docker compose down
```

---

## 環境變數

| 變數 | 說明 | Compose 預設 |
|------|------|----------------|
| `NCCM_ADMIN_USER` | Web 登入帳號 | 來自 `.env` |
| `NCCM_ADMIN_PASS` | Web 登入密碼（≥12 字元） | 來自 `.env` |
| `NCCM_NETDRIVER_URL` | Portal 連 Agent 的 URL | `http://netdriver-agent:8000` |
| `NCCM_STORE_DIR` | 備份根目錄（容器內） | `/data/store` → 掛載 `./store` |
| `NCCM_SESSION_SECRET` | Cookie 簽章（多副本請固定） | 未設則每次重啟隨機 |

**REST API**：不在 `.env` 設定；admin 於 **API Token** 頁建立 token 並參閱該頁手冊。

| `NCCM_PORT` | 對外 Web 埠 | `8501` |
| `NETDRIVER_AGENT_PORT` | 對外 Agent API 埠 | `8000` |
| `NETDRIVER_AGENT_CONFIG` | Agent 設定檔路徑（僅 Agent 容器） | `/app/config/agent/agent.yml` |

**設備 SSH 帳密**：僅在 Web「批次備份」表單輸入，**不寫入** `.env` 或映像。

Agent 設定檔（逾時、廠牌 profile）：`deploy/config/agent/agent.yml`（掛載唯讀至容器）。

---

## 設備清單 CSV

必填欄位：**`Site,IP,Vendor,Port`**

| 欄位 | 說明 |
|------|------|
| Site | 站點／機房代碼，對應 `store/<Site>/...` |
| IP | 管理 IP |
| Vendor | `cisco` / `fortinet` / `huawei`（**不含** `cisco_wlc`） |
| Port | SSH 埠，預設可填 `22` |

可選 **`Model`**、**`Version`**：留空則備份時依 `show version` / 等同指令**自動辨識**並重連 NetDriver profile。Cisco 全程 **`login`**（不送 enable）。設定備份：**NX-OS（`nexus`）** `show running-config`；**IOS（catalyst／isr 等）** `show running-config view full`。

範例：`DEMO-v3.csv`

```csv
Site,IP,Vendor,Port
hq,10.1.1.10,cisco,22
hq,10.1.1.20,fortinet,22
dc,10.2.1.5,huawei,22
```

Web 支援 **上傳 CSV** 或貼上內容；備份在背景執行，頁面以 **SSE** 顯示 log。

---

## 備份儲存結構

```
store/
├── index.db                 # SQLite 庫存索引
└── <Site>/
    └── <IP>__<Hostname>/
        └── snapshots/
            └── <UTC-timestamp>/
                ├── manifest.json
                ├── config.txt
                ├── version_info.txt
                ├── cdp_neighbors.txt   # Cisco 等
                ├── lldp_neighbors.txt
                └── interfaces.txt
```

設備在索引中的主鍵為 **`site::ip::port::hostname`**（hostname 經正規化；同 IP 不同 hostname 為不同設備）。虛擬 IP／Stack 仍只備份**一份** running-config（掛在 Active/Master 邏輯設備上）。

備份完成後會自動寫入索引；亦可於「設備總表」按 **重建索引** 掃描整個 `store/`。

---

## Web 功能（四頁）

1. **批次備份** — CSV、SSH 帳密、即時 job log；支援廠牌 **Cisco**（IOS/IOS-XE Catalyst、Stack；Nexus）、**Fortinet**、**Huawei**（不支援 WLC）  
2. **設備總表與版控** — Site／**Vendor（下拉，來自已備份設備）**／關鍵字篩選；型號／版本／序號、歷史快照、Running-Config 預覽與**下載**（完整 `config.txt`，下載旁提示可能無法直接用於還原）；**Cisco Stack / FortiGate HA** 每台實體機一行（Stack#、Role **Primary/Secondary**、各自序號；Cisco 成員 hostname 為 `管理名 · SW#`）。組態錨點列標 **· 組態**；虛擬 IP 只備一份 running-config。  
   - **Cisco Stack**：`version_info.txt` + 備份時 **`show switch` → `stack_info.txt`**（非 Nexus）  
   - **FortiGate HA**：`ha_status.txt`（Primary/Secondary 行含 hostname、serial）  
   展開異常時請重新備份後按 **重建索引**。  
3. **CDP/LLDP 鄰居** — 設備列表同總表展開 Stack/HA；由快照解析鄰居表  
4. **Device Interface Map** — 設備列表含 Stack#/Role；`config` + `interfaces` 合併埠位表  

側欄顯示 Agent **Online**／**Offline**（綠／紅），不顯示 URL 或 store 路徑。Portal 帳號存於 **`store/portal_auth.db`**（密碼雜湊）；**admin** 可進 **使用者管理**、**API Token**；**viewer** 唯讀（無批次備份／重建索引／config 下載）。**首次以 `.env` bootstrap 登入後須立即變更密碼**（`/account/change-password`）。

---

## 維運

### Docker 更新方式

#### 推薦標準更新（日常改動後）
```bash
git pull
docker compose build --no-cache
docker compose up -d
```

#### 安全完整更新（升級版本或行為異常時建議）
```bash
docker compose down
git pull
docker compose build --no-cache
docker compose up -d --build
```

#### 強制清除舊 Volume（Agent unhealthy、權限問題等）
```bash
docker compose down -v
git pull
docker compose build --no-cache
docker compose up -d --build
```

#### 僅更新 Agent
```bash
docker compose build --no-cache netdriver-agent
docker compose up -d netdriver-agent
```

#### 僅更新 Portal
```bash
docker compose build portal
docker compose up -d portal
```

#### 更新後建議檢查
```bash
docker compose ps
docker compose logs -f netdriver-agent     # 查看 Agent 是否正常啟動
```

> **重要提醒**：
> - 重大更新前建議先備份 `./store` 目錄。
> - 若本次更新涉及索引結構或 hostname 解析，更新後請在 Web 按「**重建索引**」。
> - `--no-cache` 可避免快取導致舊程式碼持續使用。
### 備份資料

請定期備份 host 目錄 **`./store`**（含 `index.db` 與所有快照）。

### Agent 日誌

```bash
docker compose logs -f netdriver-agent
```

（已移除 `agent-logs` volume：Agent 以 uid 1000 執行，掛載 root-owned volume 會導致 **unhealthy**。）

---

## 進階

### Agent 使用 host 網路（設備僅主機可達時）

編輯 `docker-compose.yml` 中 `netdriver-agent`：

```yaml
    network_mode: host
    # 移除 ports / networks 區塊（host 模式不適用）
```

並將 portal 的 `NCCM_NETDRIVER_URL` 改為 `http://127.0.0.1:8000`（portal 也需 host 網路，或依實際路由調整）。

### 本機開發（不用 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-v3.txt
cp .env.example .env
export PYTHONPATH=.
# 另終端啟動 Agent（見 netdrive-agent 文件）後：
python -m uvicorn web.main:app --reload --port 8501
```

模組說明：`nccm/`（備份、索引、解析）、`web/`（UI）。

### CLI 備份（無 Web）

```bash
export PYTHONPATH=.
export NCCM_NETDRIVER_URL=http://127.0.0.1:8000
python -m nccm backup --csv DEMO-v3.csv --user admin --password '***'
```

---

## 資安

- 勿將 `.env` 提交 Git；建議 `chmod 600 .env`  
- Web 帳密僅來自環境變數；無程式內建預設密碼  
- 登入稽核寫入 `nccm_auth.log`（路徑可經 `NCCM_AUDIT_LOG` 調整）  
- Docker 請用 `env_file: .env`，避免在命令列暴露密碼  
- **不支援** WLC；CSV 含 WLC vendor 會被拒絕  

---

## 目錄導覽

| 路徑 | 說明 |
|------|------|
| `docker-compose.yml` | 正式部署入口 |
| `docker/Dockerfile.portal` | Web 映像 |
| `netdrive-agent/` | Agent 原始碼（Compose 建置 `packages/agent/Dockerfile`） |
| `deploy/config/agent/` | 正式環境 Agent YAML |
| `nccm/` | 備份核心、索引、解析器 |
| `web/` | FastAPI + HTMX 前端 |
| `docs/NCCM-v3-spec.md` | 技術規格摘要 |
| `docs/Handbook.html` | **使用手冊**（安裝／設定／操作） |
| `legacy/` | 封存之 Streamlit 單體與舊文件 |

---

## 疑難排解

| 現象 | 處理 |
|------|------|
| 側欄 Agent 紅燈 | `docker compose ps`、Agent log、`curl http://localhost:8000/health` |
| 備份全失敗 | 確認容器到設備 **SSH 22**（或 CSV Port）可連、帳密正確 |
| 庫存只有一台 | 同 Site+IP 多設備需不同 **Port** 或 **hostname**；按「重建索引」 |
| 設備列表 Hostname 為空白／unknown | 舊快照的 hostname 可能只從 show version 抓到；新備份已優先從 running-config 解析。請按「重建索引」從現有 `config.txt` 回填。 |
| Agent **unhealthy** | 多為舊 `agent-logs` volume 權限問題：`docker compose down -v && docker compose up -d --build`；查 `docker compose logs netdriver-agent` |
| Forti 設定過短 | 調高 `deploy/config/agent/agent.yml` 內 `fortinet.fortigate` `read_timeout` |
| Cisco Nexus 備份失敗（auto classify 後） | 若 Detail 為 `[config] …: ^` 但 **CLI tail** 已有 config 與 `hostname#`，為 Agent 誤判 lone `^`（需 **rebuild netdriver-agent**）。否則查權限／`read_timeout`；**Nexus** 用 `show running-config`，**IOS** 用 `show running-config view full`（`login` 模式、不用 `enable`）。 |
| 備份失敗但 docker log 無錯誤 | 單台錯誤在 Portal **SSE 即時日誌**（含 `[config]` 與 `CLI tail`）與結果表 **Detail**；若 `FAILED —` 後為空請 rebuild portal。Agent 可設 `api.request_log_level: DEBUG` 後 `docker compose logs netdriver-agent` |

---

## 授權

MIT（與主專案相同）

*文件版本：NCCM v3 產品化 — Docker Compose + NetDriver Agent*
## API 介面

外部程式可透過 REST API 讀取庫存（與 Web 登入分離：`/api/v1` 不經 Session 閘道，以 `X-API-Key` 驗證）。

### 設定

1. 以 **admin** 登入 Portal → **API Token** 建立 token（僅建立當下顯示一次）。
2. 同一頁面下方有 **REST API 使用手冊**（端點、參數、Postman、curl）。
3. 客戶端標頭：`X-API-Key: *** token>`。

### 基本資訊

- **基礎路徑**：`/api/v1`
- **驗證**：`GET /api/v1/inventory` 需要有效 token（scope `inventory:read`）；尚無啟用中 token 時 **500**（fail-closed）。
- **回應格式**：JSON（庫存列表）
- **狀態碼**：200 成功；401 金鑰錯誤或缺失；403 scope 不足；500 伺服器未設定 token

### 已實作端點

#### 健康檢查（無需 API Key）

- **URL**：`GET /api/v1/health`
- **回應**：`{"status":"ok"}`

#### 取得庫存列表

- **URL**：`GET /api/v1/inventory`
- **查詢參數**：`site`、`vendor`、`q`、`limit`（預設 100，最大 500）、`offset`（預設 0）
- **回應**：陣列，每筆為已展開 Stack/HA 的設備列（`device_id`、`site`、`ip`、`hostname`、`vendor`、`stack_switch`、`is_config_anchor` 等）。

> **規劃中**（尚未實作）：單設備詳情、`config.txt`、備份歷史等路徑；請以 Web「設備總表」或 `GET /inventory/download/config`（需 Web 登入）取得設定檔。

### 安全注意事項

- Token 存於 `store/portal_auth.db`（雜湊）；於 **API Token** 管理頁輪替／停用；完整說明見該頁手冊。
- 生產環境建議 HTTPS 反向代理。

### 使用範例（curl）

```bash
# Portal「API Token」頁建立的 nccm_… token
export NCCM_API_TOKEN="nccm_your_token_from_portal"

curl -sS -H "X-API-Key: $NCCM_API_TOKEN" "http://localhost:8501/api/v1/inventory?limit=20"

curl -sS "http://localhost:8501/api/v1/health"
```
