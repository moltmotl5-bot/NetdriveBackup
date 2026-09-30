# DrawSwitch / SwitchDraw 與 NCCM v3 整合評估

> 使用者需求：**drawswitch merge** — 將 [SwitchDraw](https://github.com/moltmotl5-bot/switchdraw) 的 Cisco 交換器前面板埠位圖能力，與 NetdriveBackup（NCCM v3）備份／庫存流程對齊。  
> **本文件為評估與路線圖；尚未合併 SwitchDraw 原始碼。**

## SwitchDraw 是什麼？

- **版本：** v1.1.5（靜態網站，可 Netlify 部署）
- **輸入：** PuTTY 整段 `.log`（含 `show running-config`、`show interfaces status` 等指令輸出）
- **輸出：** Excel `.xlsx` 前面板圖（VLAN 色碼、Ports/VLANs 工作表）
- **執行：** 全部在瀏覽器完成；執行期依賴內附 `exceljs.bare.min.js`
- **不支援：** SVG/PNG/PDF、Huawei/Fortinet、後端 API

詳細操作請見 SwitchDraw 仓库 [README](https://github.com/moltmotl5-bot/switchdraw/blob/main/README.md)。

## NCCM v3 已有什麼？

| 能力 | 狀態 |
|------|------|
| Cisco 組態 + `show interface status` 備份 | ✅ `config.txt`、`interfaces.txt` |
| Web Interface Map（表格） | ✅ `/interfaces` |
| CDP/LLDP 鄰居 | ✅ `/neighbors`（brief 指令輸出） |
| 堆疊成員 | ✅ `stack_info.txt` + inventory |
| 前面板 Excel / 色碼圖 | ❌ |
| 從快照一鍵產圖 | ❌ |
| SVG/PNG/PDF 匯出 | ❌ |

規格摘要：[NCCM-v3-spec.md](./NCCM-v3-spec.md)

## 主要差距

1. **備份指令：** NCCM 未收集 `show interfaces description`、`show ip interface brief`、`show vlan brief`；CDP/LLDP 為 **neighbors** 而非 **neighbors detail**。
2. **資料形態：** SwitchDraw 吃「單一 log」；NCCM 存「多個 `.txt` + NCCM 標頭」→ 需要 **log 合成器** 或改寫解析器。
3. **呈現層：** NCCM 僅 HTMX 表格；SwitchDraw 的 faceplate + ExcelJS 整段缺失。
4. **範圍：** SwitchDraw 僅 Cisco IOS/XE；NCCM 多廠牌 — 整合功能應標示 **Cisco-only**。

## 建議合併策略（未在本 PR 實作）

| 方案 | 說明 | 適合時機 |
|------|------|----------|
| **文件先行（本 PR）** | 評估 + README 連結 | 避免盲目 submodule |
| **Git submodule** | `tools/switchdraw` 追 upstream tag | 要獨立維護 SwitchDraw |
| **Vendored 靜態檔** | `web/static/switchdraw/` | 單一 Docker 映像、離線 |
| **API 整合** | 擴充備份 artifact + `switchdraw-log` API + Portal 按鈕 | 與排程備份一致（推薦中長期） |

## 建議下一步（PR 序列）

1. **（可選小 PR）** 擴充 `cisco_backup_commands()`：新增 description / ip brief / vlan brief artifacts（soft-skip 與現有 interfaces/cdp 相同）。
2. **（中 PR）** 實作快照 → SwitchDraw 相容 log 的下載 API；Portal `/interfaces` 加「產生埠位圖」連至 `/tools/switchdraw/`。
3. **（可選）** 批次 XLSX：伺服器端產檔（排程／email），需另評估 openpyxl 或 Node 子程序。

## 過渡用法（現狀）

在整合完成前，運維可：

1. 從 NCCM 下載 `config.txt` 與手動補 PuTTY 其餘指令到單一 `.log`，或
2. 直接使用 SwitchDraw 依 README 從設備抓完整 log。

## 相關連結

- SwitchDraw：https://github.com/moltmotl5-bot/switchdraw  
- NCCM Interface Map 程式：`nccm/parsers/interface_map.py`、`web/templates/interfaces.html`  
- Cisco 備份指令定義：`nccm/profiles/__init__.py`

---

*本評估對應 draft PR「drawswitch merge」；完整內部差距表見專案 Agent Store `internal/switchdraw-vs-nccm-gap.md`（協調用）。*
