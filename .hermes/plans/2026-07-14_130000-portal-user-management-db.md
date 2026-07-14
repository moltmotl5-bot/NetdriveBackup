# Portal 使用者帳號管理（DB 取代 .env 明文）實作計畫

> **For Hermes:** 實作時建議用 `subagent-driven-development` 逐任務執行；本文件僅規劃，**尚未實作**。

**Goal:** 以 SQLite 儲存 Portal 使用者（密碼雜湊），提供 Web「使用者管理」頁面，逐步取代單一 `NCCM_ADMIN_USER` / `NCCM_ADMIN_PASS` 明文登入；`API_KEY` 維持機器對機器用途，不在此階段改動。

**Architecture:** 新增獨立 `portal_auth.db`（與 `store/index.db` 分離，避免重建索引誤刪帳號）；`web/auth.py` 擴充為查 DB + `bcrypt`/`argon2` 驗證；`SessionMiddleware` 的 `session["user"]` 改存 `username` + `role`；僅 `admin` 可進 `/admin/users` 與相關 API。首次啟動若 DB 無使用者，由環境變數 **一次性** 種子管理員（或 CLI `nccm users bootstrap`），之後可選擇不再要求 `NCCM_ADMIN_PASS`。

**Tech Stack:** 現有 FastAPI + Jinja2 + HTMX 風格；SQLite3（stdlib）；建議 `argon2-cffi` 或 `bcrypt`（擇一寫入 `requirements-v3.txt`）；沿用 `SessionMiddleware` + `SessionGateMiddleware`。

---

## 現況摘要（2026-07-14）

| 項目 | 現況 |
|------|------|
| 登入 | `web/main.py` `POST /login` → `load_portal_credentials()` 讀 `.env` 單一帳密 |
| 驗證 | `web/auth.py` `verify_login` **明文比對** |
| 閘道 | `SessionGateMiddleware`：`/api/v1` 放行；其餘需 `session["user"]` |
| 稽核 | README 寫 `nccm_auth.log`；**v3 `web/main.py` 尚未實作**（legacy Streamlit 有） |
| 索引 DB | `nccm/storage/index_db.py` → `store/index.db`（設備／快照） |

**範圍外（本階段）:** 設備 SSH 帳密（仍只在批次備份表單、不寫 DB）；LDAP/OIDC；多租戶 Site 權限；`API_KEY` 輪替 UI。

---

## 建議資料模型

**檔案:** `store/portal_auth.db`（或 `NCCM_AUTH_DB` 可覆寫路徑，預設與 `NCCM_STORE_DIR` 同 volume）

```sql
CREATE TABLE portal_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',  -- 第一版僅 'admin' | 'viewer'
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE INDEX idx_portal_users_active ON portal_users(is_active);
```

**密碼政策（沿用並擴充現有 `_WEAK`）:** ≥12 字元、不可等於 username、不可在弱密碼清單。

**Session 內容（建議）:**
```python
request.session["user"] = username  # 向後相容可先只改內部解析
request.session["uid"] = user_id
request.session["role"] = "admin" | "viewer"
```

---

## 遷移與啟動策略（避免鎖死現場）

1. **Phase A — 雙軌（建議先上線）**  
   - DB 有該 username → 僅驗證 hash。  
   - DB 空且 env 有 `NCCM_ADMIN_*` → 登入成功後 **可選** 自動寫入第一筆 `admin`（或顯示「請至使用者管理變更密碼」）。  
   - 仍允許 env 作為 **break-glass**（`NCCM_BOOTSTRAP_USER` / `NCCM_BOOTSTRAP_PASS` 或保留舊變數名並標 deprecated）。

2. **Phase B — 僅 DB**  
   - 文件標明：新部署只需建立 bootstrap 使用者；`NCCM_ADMIN_PASS` 從 `.env.example` 移除或改為僅 bootstrap 用。

3. **Docker:** `portal` 的 `env_file` 保留 `NCCM_SESSION_SECRET`、`API_KEY`；`NCCM_ADMIN_PASS` 改為可選。

---

## 前端「使用者管理」

| 元素 | 說明 |
|------|------|
| 導覽 | `web/main.py` `NAV` 新增一項（僅 `admin` 可見）：**使用者管理** → `/admin/users` |
| 列表 | HTMX 或整頁表格：username、role、啟用、最後登入、操作 |
| 操作 | 新增使用者、重設密碼、停用（不可刪除最後一個 active admin）、角色切換（admin ↔ viewer） |
| 自我服務 | 可選 Phase 2：`/account/password` 變更自己的密碼 |
| 權限 | `viewer`：可讀設備總表／鄰居／介面圖；**不可** 批次備份、重建索引、使用者管理、下載 config（需產品決策，見下方問題） |

**模板（預計新增）:**
- `web/templates/admin_users.html`
- `web/templates/partials/admin_users_table.html`（若 HTMX）

**樣式:** 沿用 `web/static/nccm.css`。

---

## 後端路由（草案）

| Method | Path | 說明 |
|--------|------|------|
| GET | `/admin/users` | 管理頁（admin） |
| GET | `/admin/users/partial` | 列表 fragment |
| POST | `/admin/users` | 新增 |
| POST | `/admin/users/{id}/password` | 重設密碼 |
| POST | `/admin/users/{id}/toggle` | 啟用/停用 |
| POST | `/admin/users/{id}/role` | 改角色 |

**共用:** `web/deps.py` 或 `web/auth.py`：`require_user`, `require_admin` Depends。

**登入:** `POST /login` 改為 `authenticate_portal_user(username, password)`；成功寫入 session + **恢復稽核** `nccm_auth.log`（成功/失敗、IP、username）。

---

## 檔案清單（預計變更）

| 動作 | 路徑 |
|------|------|
| 新增 | `nccm/auth/__init__.py`, `nccm/auth/db.py`, `nccm/auth/passwords.py`, `nccm/auth/service.py` |
| 新增 | `web/deps.py`（session 依賴） |
| 修改 | `web/auth.py`（薄層，委派 service） |
| 修改 | `web/main.py`（login、NAV、admin 路由、viewer 路由保護） |
| 新增 | `web/templates/admin_users.html`, `partials/...` |
| 修改 | `web/templates/base.html`（條件顯示管理連結、顯示目前使用者） |
| 修改 | `nccm/config.py`（`auth_db_path()`） |
| 修改 | `.env.example`, `README.md`, `docs/Handbook.html`, `docs/NCCM-v3-spec.md` |
| 新增 | `scripts/run-hermes-verify-portal-users.py`（ad-hoc：hash、CRUD、login、權限） |
| 修改 | `requirements-v3.txt`（argon2 或 bcrypt） |

**不建議** 把 `portal_users` 塞進 `index_db.py` 的 `_SCHEMA`（職責分離、備份還原語意較清楚）。

---

## 實作階段（建議順序）

### 階段 1 — 認證核心（無 UI）
1. `portal_auth.db` schema + migration 初始化。  
2. 密碼 hash/verify 單元（含政策）。  
3. `authenticate_user` / `create_user` / `list_users` / `set_password` / `set_active`。  
4. `POST /login` 改 DB；保留 env 雙軌 + 種子第一個 admin。  
5. Ad-hoc 腳本：建立使用者、登入 TestClient、錯誤密碼 401。

### 階段 2 — 授權與稽核
1. `require_admin`；保護備份 POST、重建索引 POST、admin 路由。  
2. 定義 `viewer` 可存取路由白名單。  
3. 登入稽核寫入 `NCCM_AUDIT_LOG`。

### 階段 3 — 使用者管理 UI
1. 列表 + 新增表單。  
2. 重設密碼、停用、角色（含「最後一位 admin」防護）。  
3. 側欄顯示 `登入者：{username}`（可選）。

### 階段 4 — 文件與維運
1. 更新 Handbook：首次部署、bootstrap、不再建議長期依賴 `.env` 密碼。  
2. Docker volume：`./store` 已掛載則 `portal_auth.db` 一併持久化。  
3. 遷移說明：既有 `.env` 使用者 → 第一次登入後自動入庫或手動 `python -m nccm users import-env`。

### 階段 5（可選）— CLI
- `python -m nccm users add|reset-password|list` 供無 Web 維運。

---

## 驗證策略

專案無 canonical pytest suite；延續 **ad-hoc `hermes-verify-*`**：

- hash 往返、弱密碼拒絕  
- TestClient：admin 登入 → `/admin/users` 200；viewer → 403  
- 停用帳號無法登入  
- env bootstrap 僅在空 DB 生效  
- **不** 在 log/assert 中輸出明文密碼  

---

## 風險與取捨

| 風險 | 緩解 |
|------|------|
| 忘記密碼且無 admin | 保留 break-glass env 或 host 上 CLI reset |
| `portal_auth.db` 未備份 | 文件列入「與 store 同卷備份」 |
| Session 固定 secret 重啟失效 | 已有 `NCCM_SESSION_SECRET` 說明 |
| 單 SQLite 多 Portal replica | 寫入衝突低機率；長期可改 Postgres（YAGNI） |

---

## 待你決策（實作前請確認）

1. **角色模型：** 第一版只要 `admin`，還是要同時上 `viewer`（唯讀）？  
2. **viewer 邊界：** 能否下載 Running-Config？能否呼叫 `/api/v1`（API Key 與 Portal 帳號是否綁角色）？  
3. **DB 位置：** `store/portal_auth.db` 是否可接受，或要獨立 volume？  
4. **遷移：** 第一次部署是否 **自動** 把現有 `NCCM_ADMIN_*` 匯入 DB，還是強制走「新增使用者」wizard？  
5. **帳號識別：** username 是否允許 email 格式、是否需顯示名稱欄位（YAGNI 可先僅 username）。

---

## 開放問題（技術）

- CSRF：表單 POST 是否加 double-submit token（FastAPI 無內建，第一版可接受 SameSite cookie + 僅內網）。  
- 密碼重設：管理員設新密碼 vs 寄送重設連結（內網產品 → 管理員重設即可）。

---

**計畫狀態:** PLAN ONLY — 未改程式碼。  
**建議下一步:** 確認「待你決策」五點後，從階段 1 Task 1（schema + hash）開始實作。