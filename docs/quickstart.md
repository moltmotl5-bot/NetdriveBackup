# NCCM v3 營運快速入門

面向**維運／值班**人員：完成安裝、設備帳號、首次備份、排程、升級與還原。細節與疑難排解請登入 Portal 後開啟 **使用手冊**（http://localhost:8501/help），或參閱 [docs/Handbook.html](Handbook.html)。

| 項目 | 說明 |
|------|------|
| 架構 | 瀏覽器 → **Portal**（8501）→ **NetDriver Agent**（Docker 內 SSH）→ 設備 |
| 資料目錄 | 主機 `./store`（快照、`index.db`、`portal_auth.db`、`schedules.db`） |
| 設備 SSH 密碼 | 僅在 Web「批次備份／排程」輸入，**不寫入** `.env` |

---

## 首次安裝

**需求：** Docker Engine 24+、Compose v2；Agent 容器須能從 Docker 網路 **SSH 至設備管理 IP:Port**。

在專案根目錄：

```bash
git clone https://github.com/moltmotl5-bot/NetdriveBackup.git
cd NetdriveBackup
cp .env.example .env
python3 -c "import secrets; print('NCCM_AGENT_HMAC_SECRET=' + secrets.token_hex(32)); print('NCCM_SESSION_SECRET=' + secrets.token_hex(32))" >> .env
# 編輯 .env：NCCM_ADMIN_PASS 至少 12 字元
chmod 600 .env
mkdir -p store
sudo chown -R 1000:1000 store
docker compose up -d --build
```

| 檢查 | 指令／URL |
|------|-----------|
| 容器狀態 | `docker compose ps` |
| 健康檢查 | `curl -s http://localhost:8501/health` |
| 登入 | http://localhost:8501/login |
| 手冊 | http://localhost:8501/help |

首次以 `.env` 的 `NCCM_ADMIN_USER`／`NCCM_ADMIN_PASS` 登入後，系統會**強制變更密碼**；之後請用 DB 內帳密（見「帳號恢復」）。

側欄 **Agent Online** 表示 Portal 可連 Agent。若 Offline：`docker compose logs netdriver-agent --tail 50`。

> **store 權限：** Portal 以 **uid 1000** 讀寫 `store/`。新安裝、還原 tarball 或升級後若目錄為 root，請再執行 `sudo chown -R 1000:1000 store`。

---

## Switch 前期設置（最低所需權限帳號設置）

NCCM 透過 **SSH** 登入設備，依廠牌執行一組 **show／display** 指令（見 `nccm/profiles`）。請在設備上建立**僅供備份**的帳號，並限制來源為 **NCCM Agent 所在網段**（Management VLAN／防火牆 ACL）。

### 共通

- CSV 必填：`Site,IP,Vendor,Port`（範例 `DEMO-v3.csv`）。
- 預設允許 SSH port **22**、**2222**；其他 port 需設 `NCCM_ALLOWED_SSH_PORTS`（見 `.env.example`）。
- **不支援 WLC**；支援 `cisco`、`huawei`、`fortinet`。

### Cisco（IOS / NX-OS）— Agent 使用 **login** 模式（通常不需 enable 密碼）

備份會執行（依型號略有差異）例如：

| 用途 | 代表指令 |
|------|----------|
| 型號／版本 | `show version` |
| 設定 | Nexus：`show running-config`；其餘 IOS 類：`show running-config view full` |
| Stack | `show switch`（非 Nexus 時） |
| 介面／鄰居 | `show interface status`、`show cdp neighbors`、`show lldp neighbors` |

**最低權限建議：** 可 SSH 登入，且上述 **exec 層 show** 不被拒。實務上常使用 **privilege 15 唯讀** 或自訂 **view／role** 僅含上述指令（勿給 `configure terminal`）。若 `show running-config view full` 被拒，備份 SSE log 的 `[config]` 會失敗—請放寬該帳號的 show 權限或改用符合政策的唯讀 role。

**Cisco 風格範例（僅示意，依 IOS-XE／NX-OS 語法調整）：**

```
username nccm-backup privilege 15 secret <強密碼>
ip ssh version 2
line vty 0 15
 transport input ssh
 access-class NCCM-AGENT-ACL in
```

### Huawei CE — Agent 使用 **enable** 模式（Portal 可填 **Enable 密碼**）

代表指令：`display version`、`display device manufacture-info`、`display stack`、`display current-configuration`、`display interface brief`、`display lldp neighbor brief`。

**最低權限建議：** SSH 帳密可進入 **enable**（或等效），且能執行上述 **display**；`display current-configuration` 需具備檢視完整設定的權限。

### Fortinet FortiGate — **enable** 模式

代表指令：`get system status`、`get system ha status`、`show full-configuration`、`get system interface physical`。

**最低權限建議：** 具 **super_admin 唯讀** 或自訂 profile 允許上述 CLI；`show full-configuration` 失敗時排程／批次皆無法取得設定檔。

### 連線驗證（營運）

1. 確認 Agent 容器到設備 **TCP/SSH** 可達（排程「上傳並連線測試」先做 **TCP probe**）。
2. 在 Portal **批次備份** 用同一組帳密試跑 **一台**，看 SSE 是否全部 artifact 成功。

更完整廠牌差異見手冊「批次備份 → 廠牌備份差異」。

---

## 首次備份

1. 登入 Portal（admin 或 operator）。
2. 側欄 **批次備份** → `/backup`。
3. 上傳 CSV 或貼上內容（格式同 `DEMO-v3.csv`）。
4. 輸入 **SSH 帳號、密碼**；Huawei／Fortinet 視需要填 **Enable 密碼**。
5. 按開始；以 **SSE** 即時查看每台 log 與結果表。

成功後資料寫入：

`store/<Site>/<IP>__<Hostname>/snapshots/<UTC>/`（含 `config.txt` 等），並更新 `store/index.db`。

6. 側欄 **設備總表與版控** 確認設備出現；必要時使用 **重建索引**。

---

## 首次設定排程備份

1. 側欄 **排程備份** → `/schedules`（需 **admin** 或 **operator**）。
2. 填 **名稱**、**間隔（日）**、**SSH 帳密**（Enable 可選，規則同批次備份）。
3. **上傳 CSV 檔案**（排程不支援純貼文字）→ **上傳並連線測試**。
4. 預覽頁顯示每台 **OK／FAIL**（TCP 探測）；**確認建立排程** 後僅 **OK** 設備納入。
5. 列表中可 **啟用** 排程；背景 watcher 約每 60 秒掃描到期任務。可先按 **立即備份** 驗證一輪。

**憑證加密：** 首次建立 **live 排程** 且需儲存 SSH 密碼時，系統可能自動建立 `store/.secrets/fernet.key`。請將 **整個 `store/`** 納入離站備份（見「災難還原」）。若 UI 提示「加密主金鑰已初始化」，請立即備份 store。

詳細按鈕說明與執行歷史見手冊「排程備份」。

---

## Switch 前期設置（最低排程備份所需權限帳號設置）

排程與批次備份共用 **同一套 Agent 指令與 SSH 模式**（見上一節「Switch 前期設置」）。排程額外注意：

| 項目 | 說明 |
|------|------|
| 帳密儲存 | 寫入 `store/schedules.db`（Fernet 密文），**不是** `.env` |
| 啟用排程 | 須已設定 Fernet 主金鑰且排程含有效帳密；否則無法啟用 |
| 探測 vs 備份 | 「連線測試」為 **TCP probe**；**SSH 帳密是否正確**以 **立即備份** 或首次 watcher 執行為準 |
| Enable | Huawei／Fortinet **必須** 在排程表單提供可進 enable 的密碼，否則 `display current-configuration`／`show full-configuration` 會失敗 |
| Cisco | 仍為 **login** 模式；排程不需填 enable，但帳號仍需能執行 `show running-config`（及 stack／鄰居等） |
| 長期營運 | 變更設備密碼後請 **編輯排程** 重填密碼；僅改設備端密碼不會更新 DB 密文 |
| 權限最小化 | 與手動備份相同：僅開放 NCCM 實際執行的 show／display；勿共用互動式維運帳號 |

若曾用 `NCCM_SECRETS_KEY` 覆寫 store 內金鑰，還原後可能 **能登入 Portal 但排程解密失敗**—見「災難還原」情境 B。

---

## 系統升級

**任何升級前先備份 `store/` 與 `.env`（或密鑰管理中的 Session／HMAC）。**

```bash
tar -czf store-backup-$(date +%Y%m%d).tar.gz store/
# 建議另存 .env 副本（勿提交 Git）

git pull origin main
docker compose build --no-cache portal
docker compose up -d --build

sudo chown -R 1000:1000 store

docker compose ps
curl -s http://localhost:8501/health
```

自舊版升級若 `store/` 仍為 root 擁有，可能無法登入或排程頁 500—執行 `chown` 後 `docker compose up -d portal`。

Agent unhealthy（舊 volume 權限）時：

```bash
docker compose down -v
docker compose up -d --build
sudo chown -R 1000:1000 store
```

（`-v` 不刪 bind mount 的 `./store`，但仍請確認已 tarball 備份。）

索引或 hostname 邏輯變更時，於 Web **設備總表 → 重建索引**。完整步驟見手冊「Docker 更新」。

---

## 重新安裝

**保留資料**（常見：換主機、重建 Docker）：

1. 備份 **`store/`** 與 **`.env`**（含 `NCCM_SESSION_SECRET`、`NCCM_AGENT_HMAC_SECRET`）。
2. 新主機安裝 Docker，clone 同版本或更新後的 repo。
3. 還原 `.env`（`chmod 600`）、還原 `store/`。
4. `sudo chown -R 1000:1000 store`
5. `docker compose up -d --build`
6. 驗證 `/health`、登入 Portal、試跑排程或批次一台。

**完全新裝（不要舊資料）：**

1. 停止容器：`docker compose down`（慎用 `-v` 若曾有 named volume）。
2. 移走或清空 `store/`，重新 `mkdir -p store && sudo chown -R 1000:1000 store`。
3. 新 `.env`（新 Session／HMAC／admin 密碼）。
4. `docker compose up -d --build`，以 bootstrap 登入並建立使用者。

重新安裝 **不會** 自動還原已遺失的 API Token 明文；Token 需於 admin 頁重建。

---

## 災難還原

與手冊「災難還原」章節一致（完整表格見 Portal **/help** 錨點 `#disaster-recovery`；`cursor/encryption-recovery-audit-c2b9`／PR #7 手冊已含該章，以下為營運摘要）。

NCCM v3 **未使用** TPM 或硬體綁定金鑰。還原問題多半來自 **`store/` 與 `.env` 未一併還原**、**`chown 1000:1000` 未做**，或 **排程 Fernet 金鑰與密文不一致**。

### 建議一併備份

1. **整個 `store/`** — `portal_auth.db`、`schedules.db`、`index.db`、`.secrets/fernet.key`、快照、`audit/` 等。
2. **`.env`（或 KMS 等價項）** — 必填：`NCCM_SESSION_SECRET`、`NCCM_AGENT_HMAC_SECRET`；若使用 secret 檔而非 store 金鑰，另備 `NCCM_SECRETS_KEY_FILE` 內容。
3. **`deploy/config/agent/`** — 若有自訂 Agent 設定。

建議定期記錄 `curl -s http://localhost:8501/health` 的 **`secrets_key_fingerprint`**（若部署含 PR #7 增強），還原後核對。

### 還原步驟（概要）

```bash
# 還原 tarball 至 ./store、還原 .env 後：
sudo chown -R 1000:1000 store
docker compose up -d --build
curl -s http://localhost:8501/health
```

確認（PR #7 起 `/health` 含 secrets 欄位）：

- `secrets_key_source` 符合預期（僅還原 store 時通常為 `store`）。
- `secrets_store_key_shadowed` **不應** 為 `true`。
- `netdriver_agent` 為 `true`。

**Fernet 主金鑰優先序（第一個命中生效）：**

1. `NCCM_SECRETS_KEY`（Compose 預設 `NCCM_ENV=production` 時，**勿**依賴 env 覆寫 store 金鑰；錯誤 env 會導致排程無法解密）
2. `NCCM_SECRETS_KEY_FILE` 或 `/run/secrets/nccm_secrets_key`
3. `store/.secrets/fernet.key`

### 常見情境（A–G 摘要）

| 代號 | 狀況 | 現象 | 修復方向 |
|------|------|------|----------|
| **A** | 只還原 store、遺失 `.env` | Compose 缺 Session／HMAC | 還原 `.env` 或重新產生並 **Portal／Agent 對齊**；登入用還原的 `portal_auth.db` |
| **B** | 還原 store 但 `.env` 含**錯誤** `NCCM_SECRETS_KEY` | 可登入；排程 decrypt 失敗 | 移除 env 覆寫，改用還原的 `fernet.key` |
| **C** | store 無 `.secrets/fernet.key` | 無法解密排程憑證 | 自完整備份補回；金鑰永久遺失則 **重建排程並重填 SSH 密碼** |
| **D** | 只還原 `.env`、store 空 | 可 bootstrap；無快照 | 還原 store |
| **E** | DB 毀損、快照仍在 | 需重建使用者 | 還原 `portal_auth.db` 或 admin bootstrap；`python -m nccm index rebuild` |
| **F** | Session secret 變更 | 全部登出 | 重新登入 |
| **G** | Agent HMAC 不一致 | 備份／排程 Agent 失敗 | 對齊 `NCCM_AGENT_HMAC_SECRET` |

**設備設定檔**（`config.txt`）為 **store 內明文**，還原 store 即可瀏覽／下載，**不依賴** Fernet。

更細機密分類與 shadow 排查可對照 PR #7 手冊「災難還原」與 `/health` 的 `secrets_*` 欄位（合併前 main 的 `/health` 可能尚無 secrets 欄位）。

---

## 帳號恢復

### Portal 日常登入

- 密碼存在 **`store/portal_auth.db`**（PBKDF2 雜湊）。
- **僅修改 `.env` 的 `NCCM_ADMIN_*` 不會更新** 已存在使用者的密碼。
- 忘記密碼：由其他 **admin** 在 **使用者管理** 重設；或還原含 `portal_auth.db` 的 store 備份。

### 首次 bootstrap（空使用者庫）

當 `portal_auth.db` **尚無使用者** 時，可用 `.env`：

- `NCCM_ADMIN_USER`
- `NCCM_ADMIN_PASS`（≥12 字元）

登入成功後寫入 DB，並**強制變更密碼**。

### Break-glass（DB 已有使用者、緊急登入）

預設 **不能** 再用 `.env` 管理員登入。緊急時：

1. 在 `.env` 設 `NCCM_BREAK_GLASS=1`（仍須知道 `.env` 內 admin 密碼）。
2. 重啟 Portal：`docker compose up -d portal`
3. 以 env 帳密登入（break-glass session），完成處置後關閉 `NCCM_BREAK_GLASS` 並重設正式帳密。

### 還原 `portal_auth.db`

1. 自備份解出 `store/portal_auth.db` 至正確路徑。
2. `sudo chown -R 1000:1000 store`
3. 重啟 Portal；以**備份當時的 Portal 密碼**登入（非當前 `.env`，除非 DB 為空走 bootstrap）。

### API Token

- 明文 token **僅建立時顯示一次**；遺失需 admin 在 **API Token** 頁停用舊 token 並新建。
- 還原舊 DB **無法** 還原已遺失的明文 token。

### 索引與設備資料（非 Portal 帳號）

若僅 auth DB 毀損但快照仍在：

```bash
# 於已安裝依賴的環境或容器內
python -m nccm index rebuild
```

---

## 下一步

| 需求 | 前往 |
|------|------|
| 角色權限、CSV 欄位、REST API | Portal **/help** |
| 開發者規格 | [docs/NCCM-v3-spec.md](NCCM-v3-spec.md) |
| Agent 本機除錯 | README「Agent 本機除錯」、`docker-compose.dev.yml` |
