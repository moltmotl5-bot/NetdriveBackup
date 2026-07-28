# NCCM v3 — PR3 安全修復 Bypass 決策紀錄

**狀態：** 已核准（刻意 defer，非遺漏）  
**適用版本：** NCCM v3（PR1+PR2、Phase 2 已合併後）  
**審查週期建議：** 每年，或管理 VLAN／設備汰換／合規稽核前

---

## 1. 決策摘要

原安全修復計畫 **PR3**（SSH host key、Agent egress allowlist、弱演算法關閉）**不在目前版本實作**。

理由：部署於 **Switch Management VLAN**，且已有 **Firewall 來源 IP 限制**；PR3 主要為深度防禦，導入成本高（fingerprint 流程、舊設備相容），現階段以 **PR1/PR2 + Phase 2 應用層控制 + 網路/營運補償** 為足。

---

## 2. PR3 跳過範圍

| 原 PR3 項目 | 目前行為 | 殘留風險 |
|-------------|----------|----------|
| **SSH host key 驗證** | Agent 使用 `known_hosts=None`（自動接受 host key） | 管理 VLAN 內 SSH 中間人（MITM）理論上可能 |
| **Agent egress allowlist** | Agent 可連線至 CSV 中任何合法 IP:Port | 若 Portal 被入侵，仍可能透過 Agent 掃描/連線 VLAN 內其他 SSH |
| **弱 KEX/cipher 關閉** | 未強制禁用弱演算法 | 舊設備若只支援弱算法，關閉會中斷備份 |

---

## 3. 已實施的補償控制（必須維持）

### 應用程式（已合併 `main`）

| 控制 | 說明 |
|------|------|
| Agent 不對外 publish | Production Compose 僅 `expose`；主機無法直連 `:8000` |
| Portal↔Agent HMAC | 未認證無法呼叫 `/api/v1/connect`、`/cmd`、`/probe` |
| CSV / store 邊界 | 惡意 Site/IP 無法 path traversal |
| Web CSRF / CSP / Session | 狀態變更 POST 需 CSRF；CSP `script-src 'self'` |

### 網路與營運（部署方責任）

| 控制 | 說明 |
|------|------|
| 管理 VLAN 隔離 | Portal / Agent 僅部署於設備管理網段 |
| Firewall allowlist | 僅允許指定來源 IP 存取 Portal（預設 8501） |
| 設備 IP 固定 | CSV 使用穩定管理 IP；變更需變更管理流程 |
| 帳號與審計 | Portal RBAC；敏感操作寫 audit（Phase 3 將補強） |
| `store/` 備份 | 快照含組態；需限制主機檔案存取權限 |

---

## 4. 明確禁止

- **不得** 以「PR3 bypass」為由重新 publish Agent port 或關閉 HMAC  
- **不得** 以 Firewall/VLAN 為由省略 CSV 驗證、store 邊界或 CSRF  
- **不得** 將 bypass 寫成「永久免做安全」；需有 owner 與下次審查日期  

---

## 5. 何時重新評估 PR3

建議啟動 PR3 實作或部分實作，若出現以下任一情況：

1. Portal 允許來源超出原設管理網段（例如 DMZ、跨 VLAN 路由）  
2. 合規要求 SSH host key 驗證或 egress 白名單（例如 ISO 27001 稽核項）  
3. 曾發生或演練發現 VLAN 內 MITM / 橫向移動風險  
4. 舊設備汰換完成，可安全關閉弱 SSH 演算法  

**若只實作子集，建議優先順序：** egress allowlist → host key → 弱演算法  

---

## 6. PR3 若將來實作時的參考驗收

（供 Phase 3 之後排程，非現行要求）

- 未知 host key 連線失敗；key 變更產生 audit  
- Agent 僅連核准 CIDR + port；拒絕 loopback / metadata IP  
- 預設 profile 無 `group1-sha1` 等弱算法；例外需文件與到期日  

---

## 7. 相關文件

| 文件 | 說明 |
|------|------|
| Portal `/help` → **已知風險與 PR3 決策** | 維運人員摘要 |
| `README.md` → 安全 | 快速對照 |
| `docs/NCCM-v3-spec.md` | 技術規格 |

**文件維護：** 變更 bypass 範圍或補償控制時，須同步更新本文件與 Handbook。
