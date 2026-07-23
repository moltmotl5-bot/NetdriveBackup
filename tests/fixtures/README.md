# Test fixtures（可提交）

此目錄僅含**去敏／合成** CLI 樣本，可進 git。

| 路徑 | 對應計畫資料 ID | 說明 |
|------|-----------------|------|
| `huawei/lldp_as_neighbor_dev.txt` | HW-LLDP-AS | `Local Intf / Neighbor Dev / Neighbor Intf / Exptime` |
| `huawei/lldp_simunet_exptime_mid.txt` | （SimuNet） | Exptime 在中間的舊欄位序 |
| `huawei/mfg_single.txt` | HW-MFG-SINGLE | 單 Slot 序號 |
| `huawei/mfg_stack_slots.txt` | HW-MFG-STACK | ≥2 Slot／serial |
| `huawei/mfg_chassis_12700_shape.txt` | HW-MFG-STACK_12700 | Chassis 表頭形狀（P0 僅契約／文件；完整解析 P1） |
| `huawei/version_s5732.txt` | HW-VER | display version 節錄 |
| `huawei/stack_cli.txt` | HW-STACK-CLI | `display stack` Slot/Role 表（P1.1 展開主來源） |
| `config/cfg_a.txt` / `cfg_b.txt` | HW-CFG 形狀 | Config Diff 合成樣本（P2） |
| `cisco/stack_show_switch.txt` | CS-STACK | show version 節錄 + show switch |
| `fortinet/ha_status.txt` | FG-HA | get system ha status 節錄 |

## 私有實機檔（不上傳）

將真實備份放在 **repo 根目錄 `testdata/*.txt`**（已 `.gitignore`）。

```bash
# 本機加跑私有樣本（不進 CI）
NCCM_PRIVATE_TESTDATA=testdata pytest -m private
```

**禁止**把 `testdata/` 或含密碼／真實 snmp community 的 config 推上 GitHub 或任何遠端。
