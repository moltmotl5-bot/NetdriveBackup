# 排程備份產品化 Implementation Plan

> **For Hermes:** PLAN ONLY until user says start building. Then use subagent-driven-development task-by-task.
> **Status:** Draft for review — **do not implement** without explicit go-ahead.
> **Branch target:** `AAA-addon` (or follow-on feature branch)
> **產品向專項計畫（HTML）：** `docs/schedule-backup-enhancement-plan.html`（排程備份 only）

**Goal:** 把現有 dry-mock「排程備份」升級為可營運的**真實排程備份**：週期觸發 → 解析 CSV → 取憑證 → 呼叫既有 `run_backup_job`／`start_backup_job_async` → 寫入快照與 `index.db` → 可觀測、可審計、可安全停用。

**Architecture:** 沿用 Portal 內 `store/schedules.db` 定義排程；執行層**不重寫備份邏輯**，統一走 `nccm/backup/runner.py` + `job_manager.py`。憑證與排程定義分離（credential store）。觸發器先強化 in-process watcher（single-instance 契約），預留 file lock／leader 旗標；可選後續拆 cron sidecar。執行記錄持久化（`schedule_runs`），UI 顯示歷史與關聯 job_id。

**Tech Stack:** FastAPI Portal、SQLite（`schedules.db` + 可選 `portal_auth.db` 或獨立 secrets）、既有 NetDriver Agent SSH 路徑、pytest、audit log（`store/audit/audit.db`）。

---

## 0. 現況與缺口

### 0.1 已有（可複用）

| 元件 | 路徑 | 能力 |
|------|------|------|
| dry-mock 排程 CRUD | `nccm/backup/schedule.py` | CSV 存 DB、間隔分鐘、enable、last_run、watcher 30s tick |
| Web UI | `web/templates/schedules.html` + `web/main.py` `/schedules*` | admin/operator；建立／mock／toggle／delete |
| 真備份 runner | `nccm/backup/runner.py` | `run_backup_job(devices, username, password, enable_password, agent_url, log)` |
| 非同步 job | `nccm/backup/job_manager.py` | `start_backup_job_async` → in-memory job + SSE `/backup/...` |
| CSV 解析 | `nccm/registry/csv.py` | `load_devices_csv` |
| 審計 | `nccm/auth/audit.py` | `write_audit` / portal events |
| 快照保留 | `nccm/storage/retention.py` | 可選：排程成功後 keep_last |

### 0.2 明確不做／未做（產品化要補）

| 缺口 | 風險 |
|------|------|
| 執行只 mock，不 SSH | 用戶誤以為已備份 |
| 無 SSH 帳密／key 綁定 | 無法真跑 |
| 全 CSV 共用一組帳密（與批次備份相同） | 多廠牌／多站點帳密不同 |
| watcher 無 leader／file lock | 多 Portal replica 雙重執行 |
| job 僅記憶體 | 重啟後歷史與進度消失；排程無法關聯 |
| 無 concurrency 控制 | 重疊觸發可能對同一設備雙備份 |
| 無失敗告警 | 沉默失敗 |
| enable_password／Cisco 規則 | 已有 runner 規則，排程須沿用 |
| 無 dry-run vs live 模式開關 | 誤觸全網 |

### 0.3 對齊文件

- Handbook 現章：`#use-schedules`（dry-mock 警告）— 產品化後必須改寫
- 舊 P2.1（`docs/AAA-addon-enhancement-plan.html`）：前置 = CSV 來源 + SSH 憑證策略 + 可選 webhook/SMTP
- 用戶記憶：per-vendor backup passwords 在 roadmap

---

## 1. 產品目標與非目標

### 1.1 目標（MVP = Phase A–C 完成即可上線 lab／單機 compose）

1. **真實執行**：啟用排程到期後，對 CSV 設備跑完整備份流程（與批次備份同品質）。
2. **憑證可配置且不進 git**：至少「每排程一組 username/password[/enable]」；設計預留 per-vendor。
3. **可觀測**：每次 run 有 run_id／job_id、成功/失敗台數、錯誤摘要、審計事件。
4. **安全預設**：新建預設 `mode=dry_mock` 或 `enabled=0` 直到綁定憑證並明確選 `mode=live`；live 需二次確認。
5. **不重疊**：同一 schedule 同時只允許一個 live run；全域可設定 max concurrent backup jobs。
6. **單實例契約**：文件 + 可選 file lock；compose 單 portal 為正式支援拓撲。
7. **角色**：admin/operator 管理；viewer 唯讀看狀態（可選 Phase C）。

### 1.2 非目標（明確延後）

- 完整 crontab 表達式／時區複雜排程 UI（MVP 維持 every_N_minutes 或 daily HH:MM 二選一）
- 分散式多 Portal leader election（K8s lease）— 僅文件 + flock
- SMTP／Teams／webhook 完整通知中心（MVP 可只 audit + last_result；通知 = Phase D）
- SSH private key 登入（Phase D；需 NetDriver 支援確認）
- 跨站點 CMDB 同步設備清單
- 自動 retention 與排程強綁（可選 hook，非必須）
- 已移除的鄰居拓撲相關

---

## 2. 需產品確認的決策（實作前勾選）

| ID | 決策 | 建議預設 | 選項 |
|----|------|----------|------|
| D1 | 排程表達 | **A** every_minutes（沿用）+ 可選 quiet hours | B: daily at HH:MM UTC；C: cron 字串 |
| D2 | 憑證模型 | **A** 每排程一組 user/pass/enable | B: 全域 env 預設 + 排程覆寫；C: credential 具名庫 + 排程引用 id；D: per-vendor map |
| D3 | 密文存放 | **A** Fernet（key = `NCCM_SECRETS_KEY` env）存於 DB blob | B: 僅 env 不存 DB；C: 外部 vault |
| D4 | CSV 來源 | **A** 繼續 DB 內 csv_text | B: store 路徑引用 `store/schedules/<id>.csv`；C: 上傳檔 |
| D5 | 重疊策略 | **A** skip if previous still running | B: queue；C: cancel previous |
| D6 | 失敗策略 | **A** 記錄 per-device，不中止整批（同 runner） | — |
| D7 | 成功後 retention | **A** 不自動 | B: 排程可選 keep_last |
| D8 | Viewer | **A** 可看列表與 last_result，無按鈕 | B: 完全不可見 |
| D9 | 「立即執行」 | **A** live 需 confirm；保留「立即 dry-mock」 | — |
| D10 | 多 Portal | **A** 正式支援 = 單 replica + flock 防呆 | B: 不做 lock 只寫 Handbook |

**建議凍結 MVP：** D1=A, D2=A→演進 C, D3=A, D4=A, D5=A, D7=A, D8=A, D10=A。

---

## 3. 目標架構

```
┌─────────────────────────────────────────────────────────┐
│ Portal (single replica)                                 │
│  ┌──────────────┐   due?    ┌─────────────────────────┐ │
│  │ schedule     │──────────▶│ schedule_executor       │ │
│  │ watcher      │           │  - resolve credentials  │ │
│  │ (30s tick +  │           │  - load CSV → devices   │ │
│  │  flock)      │           │  - start_backup_job_    │ │
│  └──────────────┘           │    async / run_backup   │ │
│         │                   │  - write schedule_runs  │ │
│         │                   │  - write_audit          │ │
│         ▼                   └───────────┬─────────────┘ │
│  store/schedules.db                     │               │
│  store/schedule.lock                    ▼               │
│                              job_manager (memory)       │
│                              + optional job meta in DB  │
└─────────────────────────────────────────┬───────────────┘
                                          │ SSH via
                                          ▼
                                   NetDriver Agent
                                          │
                                          ▼
                                      devices
                                          │
                                          ▼
                               store/<site>/.../snapshots
                               store/index.db
```

### 3.1 資料模型（建議）

**`schedules` 表擴充（migration 相容舊列）：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| id, name, csv_text, every_minutes, enabled, … | 既有 | 保留 |
| mode | TEXT | `dry_mock` \| `live`（預設 `dry_mock`） |
| credential_id | INT NULL | FK → credentials（若 D2=C） |
| username | TEXT | D2=A 時用；勿存 password 明文 |
| password_enc | BLOB/TEXT | Fernet token |
| enable_password_enc | BLOB/TEXT | 可空 |
| running_job_id | TEXT | 進行中 job；完成後清或留 last |
| last_job_id | TEXT | |
| last_ok_count / last_fail_count | INT | |
| next_run_at | TEXT | 可選，便於 UI |
| created_by | TEXT | portal user |
| notes | TEXT | |

**新表 `schedule_runs`：**

| 欄位 | 說明 |
|------|------|
| id | PK |
| schedule_id | |
| started_at / finished_at | UTC ISO |
| mode | dry_mock \| live |
| job_id | 對應 job_manager |
| run_id | runner 的 backup run_id |
| status | running \| done \| failed \| skipped |
| ok_count / fail_count / device_count | |
| summary | 短文字 |
| detail_json | 可選 per-device 摘要（截斷） |
| triggered_by | `watcher` \| `manual` \| `user:admin` |

**新表 `backup_credentials`（若 D2=C，推薦中期）：**

| 欄位 | 說明 |
|------|------|
| id, name, username | |
| password_enc, enable_password_enc | |
| vendor_scope | `*` 或 `cisco,huawei` |
| created_by, updated_at | |
| last_used_at | |

舊 dry-mock 列：`mode=dry_mock`，無密碼仍可 mock。

### 3.2 執行語意

```
tick:
  acquire store/schedule.lock (non-blocking) or skip tick
  for each enabled schedule where due:
    if mode=live and running_job_id active: skip (D5=A)
    if mode=live and missing credentials: mark error, audit fail, skip
    create schedule_runs row status=running
    if mode=dry_mock:
      mock_run_csv → update last_* → runs done
    else:
      devices = load_devices_csv
      job_id = start_backup_job_async(devices, user, pass, enable)
      store running_job_id
      # completion: either poll in watcher or callback hook when job ends
      on job terminal:
        update runs, last_result, clear running_job_id
        write_audit snapshot_backup_schedule
        optional notify
```

**完成回報：** MVP 在 watcher 內輪詢 `get_job(job_id)` 直到 done/failed（避免大改 job_manager）；較佳是 `job_manager` 加 `on_complete` callback（Phase B）。

### 3.3 與批次備份一致性

- **必須**呼叫同一 `run_backup_job`／async 包裝，禁止複製 SSH 邏輯。
- Cisco enable 規則維持 `runner._enable_password_for_vendor`。
- Agent URL：`netdriver_url()` 與批次相同。
- 成功後索引行為與現況一致（runner 既有寫 store／index）。

---

## 4. 安全與合規

1. **密碼永不進 git、不進 SSE 明文 log**；job log 禁止印 password。
2. **Fernet key**：`NCCM_SECRETS_KEY`（urlsafe base64 32 bytes）；缺 key 時 live 建立失敗並提示。
3. **UI**：編輯排程時 password 欄空白 = 保留原密文；輸入新值才旋轉。
4. **API**：若未來有 REST 排程，禁止回傳解密密碼；僅 `password_set: true/false`。
5. **審計事件（建議）**  
   - `schedule_create` / `schedule_update` / `schedule_delete` / `schedule_toggle`  
   - `schedule_run_start` / `schedule_run_finish`（含 mode, ok/fail, job_id）  
   - `schedule_run_skipped`（仍在跑／缺憑證）
6. **權限**：mutate = operator+；live 立即執行可限 admin（可選，預設 operator 可）。
7. **Handbook**：明文警告 compose secrets、key 備份、rotate 流程。

---

## 5. UI／UX 產品化

### 5.1 `/schedules` 頁

- 列表欄：名稱、模式（mock/live badge）、間隔、啟用、上次執行、結果（ok/fail）、進行中 job 連結。
- 建立／編輯表單：
  - 名稱、CSV、every_minutes
  - mode 單選：`僅解析（dry-mock）` / `真實備份（live）`
  - 憑證：username、password、enable_password（live 必填 user+pass）
  - 說明文字：與批次備份相同限制（一組帳密套整份 CSV）
- 按鈕：
  - **立即 dry-mock**（永遠安全）
  - **立即真實備份**（confirm 文案含設備約略台數）
  - 啟用／停用、刪除、編輯
- 詳情／展開：最近 N 次 `schedule_runs`；live 成功可連到 inventory 篩選（可選）。

### 5.2 批次備份頁

- 短註：週期性請用排程；此頁為 ad-hoc。

### 5.3 側欄／角色

- viewer：可讀列表 + runs（D8=A）或隱藏（D8=B）。

---

## 6. 實作分期（建議）

### Phase A — 資料與安全基礎（不接真備份）

**成果：** schema migration、加密 helper、mode 欄位、UI 顯示 mode、仍可 mock。

1. `nccm/backup/secrets.py`：Fernet encrypt/decrypt；env key loader  
2. `schedules` ALTER／建表兼容；`schedule_runs`  
3. CRUD 擴充 create/update（含 password_enc）  
4. UI：mode badge；建立時選 mode（live 無 key 則拒絕）  
5. 測試：加解密、migration、舊列預設 dry_mock  
6. 審計：create/update/delete  

**完成定義：** 不開 live 行為與今日 mock 相容；pytest 綠。

### Phase B — Live 執行串 runner

**成果：** watcher／手動可 live → 真備份。

1. `schedule_executor.py`：`execute_schedule(id, triggered_by, force_mode=None)`  
2. 整合 `start_backup_job_async`；completion 輪詢或 callback  
3. D5 skip if running；due 邏輯沿用  
4. flock `store/schedule.lock` 包住 tick  
5. `last_result` 格式：`live ok=3 fail=1 job=… run=…`  
6. UI：立即真實備份 + confirm  
7. 測試：mock devices 層用 monkeypatch `run_backup_job` 不碰真 Agent  
8. audit run_start/finish  

**完成定義：** lab CSV + 測試 monkeypatch 全路徑；文件標註需 Agent。

### Phase C — 可觀測與營運 UX

1. runs 歷史表 UI  
2. viewer 唯讀（若 D8=A）  
3. job 頁或 schedules 顯示 running 狀態（polling HTMX 可選）  
4. Handbook／README 全面改寫 dry-mock → 產品行為  
5. 失敗時 UI 紅色摘要；可選「複製失敗 IP」  
6. 與 retention 的**文件**建議（手動或另 job），不強制 auto  

### Phase D — 增強（可另開 epic）

1. 具名 credential 庫 + 排程引用（D2=C）  
2. per-vendor password map（用戶 roadmap）  
3. daily HH:MM 或 cron  
4. webhook/SMTP 通知  
5. SSH key（依賴 Agent）  
6. 排程成功後 optional keep_last  
7. 持久化 job log 到 `store/jobs/`  
8. 多實例 leader（若有 HA 需求）

---

## 7. 建議檔案變更清單（實作時）

| 動作 | 路徑 |
|------|------|
| Modify | `nccm/backup/schedule.py` — schema、CRUD、due、不再把 live 當 mock |
| Create | `nccm/backup/secrets.py` |
| Create | `nccm/backup/schedule_executor.py` |
| Modify | `nccm/backup/job_manager.py` — optional on_complete；勿把密碼寫入 log |
| Modify | `web/main.py` — routes create/update/run live |
| Modify | `web/templates/schedules.html` |
| Create | `web/templates/partials/schedule_runs.html`（C） |
| Modify | `nccm/auth/audit.py` — 若需新 helper |
| Test | `tests/backup/test_schedule.py` 擴充 |
| Create | `tests/backup/test_schedule_live.py`（mock runner） |
| Create | `tests/backup/test_secrets.py` |
| Modify | `docs/Handbook.html`、`README.md` |
| Modify | `.env.example` — `NCCM_SECRETS_KEY=` 說明 |
| Optional | `deploy/config` 註解 |

---

## 8. 測試策略

| 層級 | 內容 |
|------|------|
| Unit | Fernet roundtrip；due 邊界；skip when running；mode 預設 |
| Unit | executor + monkeypatch `start_backup_job_async` / `run_backup_job` |
| Unit | 缺憑證 live → 不呼叫 runner |
| Unit | flock：第二 tick 拿不到 lock 不雙跑（可用 tmp lock path） |
| Integration | 可選 `NCCM_PRIVATE_TESTDATA` + lab — **不進 CI 預設** |
| 回歸 | 既有 `test_schedule` mock 路徑仍過 |
| 手動 UAT | compose up → 建 dry 排程 → 立即 mock → 設 key 與 live → 1 台 lab → 查 inventory 新快照 + audit |

**禁止：** 測試寫死真實密碼進 git；用 monkeypatch 或 env。

---

## 9. 文件與發布檢查表

- [ ] Handbook `#use-schedules` 去掉「僅 mock」為主敘事；保留 mock 為模式之一  
- [ ] README Web 功能列表  
- [ ] `.env.example` secrets key 產生方式：`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`  
- [ ] 升級說明：舊 schedules 自動 `mode=dry_mock`；要 live 需編輯加憑證  
- [ ] 明確：**官方支援單 Portal 副本**；多副本需關其他 watcher 或自擔風險  
- [ ] 審計事件列入 admin audit 篩選說明  

---

## 10. 風險與緩解

| 風險 | 緩解 |
|------|------|
| 誤開 live 打全網 | 預設 dry_mock；live confirm；enabled 預設 off 可討論 |
| 密碼洩漏於 log | code review 檢查點；log redaction 測試 |
| 長備份 > every_minutes | D5 skip；UI 顯示 running |
| Agent 掛掉 | runner 既有錯誤；runs failed + audit |
| DB 無 migration 工具 | 啟動時 `ENSURE_SCHEMA` 幂等 ALTER |
| cryptography 依賴 | 加入 pyproject/requirements；image rebuild |
| 與「每廠牌密碼」期待落差 | MVP 文件寫清一組帳密；Phase D map |

---

## 11. 工作量粗估

| Phase | 約略 |
|-------|------|
| A 資料+加密+UI mode | 0.5–1 d |
| B live executor+lock+tests | 1–1.5 d |
| C runs UI + docs | 0.5–1 d |
| D 各項 | 另估 |

MVP（A+B+C 核心）≈ **2.5–4 工程日**（含文件與 pytest，不含 lab 實機調通）。

---

## 12. 驗收標準（MVP Done）

1. 可建立 `dry_mock` 排程，行為與現況一致（解析 CSV、不 SSH）。  
2. 設定 `NCCM_SECRETS_KEY` 後可建立 `live` 排程並保存加密密碼；DB/API/UI 不見明文。  
3. 「立即真實備份」與 watcher 到期皆能觸發與批次相同之備份；成功設備在 inventory 可見新快照。  
4. 同一排程重入時 skip 或明確拒絕，不平行雙跑。  
5. `schedule_runs` 或至少 last_result 可區分 ok/fail 計數；audit 有 run 事件。  
6. `pytest -m "not private"` 全綠；Handbook/README 已更新。  
7. 無 `NCCM_SECRETS_KEY` 時無法啟用 live（有清楚錯誤）。

---

## 13. 建議實作任務切片（開始 build 後用）

> 每任務 宜小步 TDD；此處僅目錄，**現在不執行**。

1. Add `cryptography` dep + `secrets.py` + tests  
2. Schema ensure: mode, password_enc, schedule_runs  
3. Extend create_schedule / update_schedule API  
4. UI form fields + password keep-on-blank  
5. executor dry path writes schedule_runs  
6. executor live path monkeypatch test  
7. Wire watcher to executor + flock  
8. Manual live button + confirm  
9. Audit events  
10. Handbook/README/.env.example  
11. UAT checklist on lab  
12. Commit/push on user request  

---

## 14. 開放問題（請用戶回覆後再開 build）

1. MVP 憑證要 **每排程一組（D2=A）** 還是直接做 **具名憑證庫（D2=C）**？  
2. 排程要不要 **一開始就 per-vendor 密碼**（否則多廠牌 CSV 仍要拆排程）？  
3. 間隔是否維持 **only every_minutes**，或要 **每天固定時刻**？  
4. Viewer 要不要看得到排程狀態？  
5. live 預設 **新建即 enabled** 還是 **enabled=0 待手動開啟**？  
6. 是否需要 **成功後自動 keep_last**？

---

**下一步：** 用戶確認 §2 決策與 §14 答案後，回覆 **start building**（或指定只做 Phase A）。在此之前不改業務程式碼。
