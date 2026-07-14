# 安全 API Token（取代單一 `API_KEY`）實作計畫

> **For Hermes:** 實作時建議用 `subagent-driven-development` 逐任務執行；本文件僅規劃，**尚未實作**。

**Goal:** 將 `/api/v1` 的單一環境變數 `API_KEY` 明文，升級為可輪替、可稽核、僅存雜湊的 **API Token** 機制；與 Portal Session 登入、Portal 使用者 DB **分離**；維持 fail-closed 與現有 `X-API-Key` 標頭相容（漸進遷移）。

**Architecture:** 在 `store/portal_auth.db`（或獨立 `api_tokens.db`，見決策）新增 `api_tokens` 表；啟動時可從 `.env` 的 `API_KEY` **一次性匯入**第一枚 token（標記 `legacy_env_import`）；驗證路徑改為 hash + `secrets.compare_digest`；僅 **admin** 在 Web「API Token 管理」建立／停用／輪替；讀取端點依 **scope** 授權（第一版至少 `inventory:read`）。

**Tech Stack:** 現有 FastAPI `web/api.py`；SQLite3；密碼學用 stdlib `hashlib.pbdkf2_hmac`（與 Portal 密碼一致）或統一改 `secrets.token_urlsafe(32)` 明文僅顯示一次；沿用 `SessionGateMiddleware` 對 `/api/v1` 放行、由 Depends 驗證 token。

**Branch 建議:** 在 `AAA-addon` 之後開 `feature/api-tokens` 或延續 `AAA-addon`（與 Portal 使用者同一產品線）。

---

## 現況摘要（2026-07-14）

| 項目 | 現況 |
|------|------|
| 設定 | `.env` 單一 `API_KEY` 明文 |
| 驗證 | `web/api.py` `_get_api_key`：`os.environ["API_KEY"]` 與 `X-API-Key` **字串相等比對** |
| 未設定 | `API_KEY` 缺失 → **500**（fail-closed，不靜默開放） |
| 閘道 | `SessionGateMiddleware` **不**攔 `/api/v1`；與 Web Session 無關 |
| 文件 | README、Handbook、`docs/NCCM-v3-spec.md`、Postman 範例皆描述單一 key |
| 測試 | `scripts/run-hermes-verify-api-key.py` ad-hoc |
| Portal | `AAA-addon` 已實作 `portal_auth.db`、admin／viewer；**API 尚未納入 DB** |

**痛點:** 無法多客戶端獨立金鑰、無法停用單一整合而不影響全部、輪替需改 `.env` 並重啟、明文落在環境與備份風險、無使用稽核。

---

## 威脅與設計原則

1. **永不儲存明文 token**（建立時顯示一次，其後僅 hash）。
2. **常數時間比對**（`hmac.compare_digest` 或對 derived secret 比對）。
3. **預設拒絕**：無有效 token、停用 token、scope 不足 → **401**；伺服器完全無可用 token 設定 → **500**（維持現行行為）。
4. **與 Portal 密碼分離**：API token 不可登入 Web Session。
5. **最小權限**：第一版 scope 僅 `inventory:read`；未來 `backup:trigger` 等需另開計畫。
6. **YAGNI**：不做 OAuth2、JWT refresh、mTLS、per-IP ACL（Phase 2 再評估 rate limit）。

---

## 建議資料模型

**首選：** 與 Portal 同檔 `store/portal_auth.db`（同一 volume、同一備份策略），表名 `api_tokens`。

```sql
CREATE TABLE api_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,                    -- 人類可讀，如 "postman-uat", "monitoring"
  token_prefix TEXT NOT NULL,            -- 前 8 字元，用於列表辨識（非秘密）
  token_hash TEXT NOT NULL UNIQUE,       -- PBKDF2 或 SHA256(token + pepper)
  scopes TEXT NOT NULL DEFAULT 'inventory:read',  -- 逗號分隔
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  created_by TEXT,                       -- portal username
  last_used_at TEXT,
  expires_at TEXT                        -- NULL = 不過期；Phase 1 可全 NULL
);
CREATE INDEX idx_api_tokens_active ON api_tokens(is_active);
CREATE INDEX idx_api_tokens_prefix ON api_tokens(token_prefix);
```

**Token 格式（建議）:** `nccm_` + `secrets.token_urlsafe(32)`（建立 API 回傳完整字串一次）。

**驗證流程:**
1. 讀 `X-API-Key`（保留標頭名，文件可加註未來支援 `Authorization: Bearer` 為別名）。
2. 依 prefix 縮小候選（或全表掃描若 token 數 < 50，YAGNI 先 prefix 索引）。
3. 對候選列 `verify_hash(presented, stored)`。
4. 更新 `last_used_at`（節流：例如每 5 分鐘最多寫一次，避免 hot path 寫爆 DB）。

**Pepper（可選）:** `NCCM_API_TOKEN_PEPPER` 環境變數，未設則僅 hash(token)；設了則 hash(token + pepper)，防 DB 洩漏後離線撞庫。

---

## 與現有 `API_KEY` 遷移

| 階段 | 行為 |
|------|------|
| **Phase A — 雙軌** | DB 有 active token → 接受任一有效 token hash；**同時**若 `API_KEY` 環境變數存在且請求 key 與其相等 → 仍接受（deprecated 日誌）。首次啟動且 `api_tokens` 空、env 有 `API_KEY` → 可選自動插入一筆 `name=env-bootstrap`、`scopes=inventory:read`（hash 儲存，**不**再依賴 env 比對）。 |
| **Phase B — 僅 DB** | 文件標明移除 `API_KEY`；compose 不再要求；admin 在 UI 輪替。 |
| **Break-glass** | 保留 env `API_KEY` 只讀到 Phase B 結束；或改為 `NCCM_API_BOOTSTRAP_KEY` 僅空庫時有效。 |

**向後相容:** Postman／腳本仍用 `X-API-Key: <secret>`，無須改 URL。

---

## 後端模組（預計）

| 路徑 | 職責 |
|------|------|
| `nccm/auth/api_tokens.py` | 產生 token、hash、verify、CRUD、list |
| `nccm/auth/db.py` | migration 新增 `api_tokens` 表 |
| `web/api.py` | `_get_api_token` 取代 `_get_api_key`；注入 `scopes` 檢查 |
| `web/admin_api_tokens.py` | `/admin/api-tokens` 路由（admin only） |
| `web/deps.py` | 可選 `require_scope("inventory:read")` |

**稽核:** 沿用或擴充 `store/nccm_auth.log` → `api_token_used` / `api_token_created` / `api_token_revoked`（IP 可選）。

---

## Web「API Token 管理」（admin）

| 元素 | 說明 |
|------|------|
| 導覽 | `NAV` 或 admin 子區：**API Token** → `/admin/api-tokens` |
| 列表 | name、prefix、scopes、啟用、建立者、最後使用、到期 |
| 建立 | 表單 name + scopes（預設勾選 inventory:read）→ 建立後 **一次性** 顯示完整 token + 複製提示 |
| 操作 | 停用（不刪列，保留稽核）、可選「輪替」（建新 + 停舊） |
| 安全 | 列表永不顯示完整 secret；僅 prefix |

**viewer** 不可進入此頁（與使用者管理相同 `require_admin`）。

---

## API 端點行為（第一版）

| 方法 | 路徑 | Auth | 說明 |
|------|------|------|------|
| GET | `/api/v1/inventory` | token + `inventory:read` | 現有行為不變 |
| GET | `/api/v1/health` | **無** 或 optional | 維持輕量健康檢查（需決策：是否洩漏「API 已設定」） |

**錯誤碼:** 401 無效／缺失 token；403 scope 不足；500 無任何可用 token 來源（DB 空且 env 未設）。

---

## 設定與文件變更（實作時）

- `.env.example`：`API_KEY` 改註解為 bootstrap／deprecated；新增 `NCCM_API_TOKEN_PEPPER` 可選說明。
- `README.md`、`docs/Handbook.html`、`docs/NCCM-v3-spec.md`：多 token、管理 UI、輪替步驟。
- Postman collection：變數 `apiKey` 不變；加一節「向 admin 申請 token」。
- `docker-compose.yml`：Phase A 仍可傳 `API_KEY`；Phase B 移除。

---

## 實作任務拆解（建議順序）

### Phase 1 — 核心（可上線）

1. DB migration + `api_tokens` model + hash/verify 單元（ad-hoc script）。
2. `web/api.py` 驗證改 DB + env 雙軌 + compare_digest。
3. env bootstrap 匯入第一枚 token（可設定關閉 `NCCM_API_IMPORT_ENV=0`）。
4. Admin UI：列表、建立（一次性顯示）、停用。
5. 更新 `run-hermes-verify-api-key.py` → `run-hermes-verify-api-tokens.py`（DB token + env 雙軌 + 401/500）。
6. 文件三處 + `.env.example`。

### Phase 2 — 強化（可選）

- `expires_at` 強制與 UI 提醒。
- `last_used_at` 節流寫入 + 列表顯示。
- Rate limit（middleware 或 reverse proxy 文件化）。
- `Authorization: Bearer` 別名。
- 獨立 `api_audit.log`。

### Phase 3 — 進階（範圍外除非明確要求）

- Per-site / per-vendor 資料範圍。
- 寫入 API（觸發備份）與更高 scope。
- HashiCorp Vault / K8s secret 同步。

---

## 測試與驗收

| 檢查 | 預期 |
|------|------|
| 無 token 來源 | `GET /api/v1/inventory` → 500 |
| 錯誤 key | 401 |
| 有效 DB token | 200 + JSON 陣列 |
| 停用 token | 401 |
| env `API_KEY` Phase A | 仍 200（並寫 warning log） |
| admin 建立 token | 僅建立當下回傳明文一次 |
| viewer | `/admin/api-tokens` → 403 |
| Portal Session | 帶 cookie 打 `/api/v1` 仍須 `X-API-Key`（不混用） |

---

## 風險與緩解

| 風險 | 緩解 |
|------|------|
| 遷移漏設 token 導致整合全斷 | Phase A 雙軌 + 啟動日誌列出 active token 數 |
| DB 與 index 備份不含 auth | 文件強調 `portal_auth.db` 必備份 |
| Token 建立後使用者未存 | UI 強制「我已複製」checkbox 才關閉 modal（可選） |
| 效能 | token 數量預期 < 20；prefix 查詢足夠 |

---

## 待產品確認（實作前可默認）

1. **DB 位置：** 與 `portal_auth.db` 同檔（**建議預設**）vs 獨立 `api_tokens.db`？
2. **Phase A 雙軌 env `API_KEY` 持續多久？** 建議至少一個小版本並在 log 打 deprecated。
3. **`GET /api/v1/health` 是否需 token？** 建議維持公開（僅 `{"status":"ok"}`）。
4. **是否強制 token 到期？** Phase 1 建議否（`expires_at` NULL）。
5. **是否允許 admin 在 UI「重新顯示」舊 token？** 建議否，只能輪替新建。

---

## 參考檔案

- `web/api.py` — 現有 `_get_api_key`
- `web/main.py` — `SessionGateMiddleware` `/api/v1` 放行
- `nccm/auth/` — Portal 使用者模式可複製
- `scripts/run-hermes-verify-api-key.py`
- `README.md` § REST API、`docs/Handbook.html` § API_KEY

---

**狀態:** Phase 1 **已實作**（2026-07-14）。