# Inventory / API 欄位契約（NCCM v3 · AAA-addon）

> 對齊 `web/api.py` · `GET /api/v1/inventory` 與設備總表顯示列。  
> 變更 API 回傳時請同步本文件與 `tests/auth/test_api_tokens.py`。

## 認證

| 項目 | 說明 |
|------|------|
| Header | `X-API-Key: <plain-token>` |
| 來源 | **僅** `store/portal_auth.db` 的 active API token（admin 於 Portal 建立） |
| Scope | 預設 `inventory:read`；缺 scope → 403 |
| 無任何 active token | `500`（`API token not configured on server`） |
| 錯誤／缺 key | `401` |
| `.env` `API_KEY` | **不再生效**（回歸測試鎖定） |
| Health | `GET /api/v1/health` 無需 key → `{"status":"ok"}` |

## Query 參數

| 參數 | 說明 |
|------|------|
| `site` | 站點篩選 |
| `vendor` | 廠牌篩選 |
| `q` | 自由文字（IP／hostname／model／serial） |
| `limit` | 1–500，預設 100 |
| `offset` | 略過筆數 |

## 回傳：陣列 of object

每列為**展開後**的顯示列（Cisco stack / Forti HA / Huawei multi-slot 可能多列）。

| 欄位 | 型別 | 語意 |
|------|------|------|
| `device_id` | int/str | 邏輯設備 id |
| `site` | string | 站點 |
| `ip` | string | 管理 IP |
| `port` | int | SSH port |
| `hostname` | string | 主機名（member 可能不同） |
| `vendor` | string | Cisco / Huawei / Fortinet … |
| `sw_version` | string | 軟體版本（**不是** serial） |
| `model_summary` | string | 型號摘要 |
| `serial_summary` | string | **序號**（Huawei：來自 `manufacture_info`，非 version 內 SW） |
| `snapshot_count` | int | 快照數 |
| `stack_switch` | int/null | Stack／HA 成員序號（1-based 顯示用） |
| `stack_role` | string | Primary / Member / Active … |
| `is_config_anchor` | bool | 是否為組態錨點成員 |
| `cluster_type` | string | `stack` / `ha` / 空 |

## 廠牌注意

| 廠牌 | serial_summary | 展開條件（現行） |
|------|----------------|------------------|
| Cisco | show version / stack serial | `stack_info.txt`（show switch）≥2 members |
| Fortinet | HA member serial | HA A-P 雙機 |
| Huawei | **manufacture-info Serial-number**（展開列）／彙總列同 | **`display stack` → stack_info.txt** ≥2 members；manufacture 只補 Slot serial／model，**不**單獨展開 |
| Huawei S12700 Chassis | manufacture 彙總；勿當 iStack | 無 display stack 則一列（soft-skip） |

## 測試入口

```bash
# 正式（可進 CI）
pip install -r requirements-dev.txt
pytest

# 本機私有實機檔（不上傳）
NCCM_PRIVATE_TESTDATA=testdata pytest -m private

# 既有 ad-hoc（保留）
python scripts/run-hermes-verify-huawei-lldp.py
python scripts/run-hermes-verify-huawei-manufacture.py
python scripts/run-hermes-verify-huawei-stack.py
python scripts/run-hermes-verify-netdriver-payload.py
python scripts/run-hermes-verify-api-tokens.py
```

## Smoke（Compose）

見 `scripts/smoke-compose.sh`（需已 `docker compose up`）。
