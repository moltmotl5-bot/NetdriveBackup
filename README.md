# AutoSwitchBackup2 — 企業級網路設備 NCCM（精簡部署版）

本目錄為 **AutoSwitchBackup** 專案的**可部署副本**，僅含執行 Streamlit 入口與 CDP/LLDP 鄰居功能所需檔案，不含開發用測試腳本、拓撲繪圖模組或本機 `venv`／歷史備份資料。

## 功能

* **批次備份：** Cisco / Huawei（Netmiko），輸出至 `output/`
* **設備總表與版控：** 解析 `version_info.txt`（含 **Cisco NX-OS**，例如 `Nexus9000 C9504`）
* **CDP/LLDP 鄰居：** 側欄第三項；Cisco 且 CDP 成功時不併入 LLDP

## 目錄內容

| 檔案 | 說明 |
|------|------|
| `app.py` | Streamlit 主程式 |
| `cdp_lldp_neighbors.py` | CDP/LLDP 解析與鄰居目錄 |
| `requirements.txt` | Python 依賴 |
| `.env.example` | 登入帳密範本（複製為 `.env`） |
| `DEMO.csv` | 設備清單格式範例（上傳時欄位需含 Site, IP, Vendor） |
| `output/` | 備份輸出目錄（執行後自動寫入） |

## 快速開始

```bash
cd /Users/claw/workspace/AutoSwitchBackup/AutoSwitchBackup2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 編輯 NCCM_ADMIN_USER / NCCM_ADMIN_PASS
streamlit run app.py
```

登入後使用左側欄：**批次備份**、**設備總表與版控**、**CDP/LLDP 鄰居**。

## 備份目錄結構

```
output/
└── [Site]/
    └── [IP]_[Hostname]/
        └── YYYY-MM-DD_HHMM/
            ├── config.txt
            ├── version_info.txt
            ├── cdp.txt
            └── lldp.txt
```

## 與 AutoSwitchBackup 主專案差異

主專案 (`../AutoSwitchBackup`) 另含 `parse_topology.py`、`drawio.py`、各類 `test_*`／驗證腳本及完整 `output` 樣本。本副本**僅同步維運入口**；進階拓撲或實驗功能請在主專案開發後再手動複製必要檔案至此。

## 資安

* 勿將 `.env` 提交至 Git（已列入 `.gitignore`）
* SSH 設備帳密僅在備份頁面輸入，不寫入磁碟

## 授權

MIT（與主專案相同）

*最後更新：2026-06-30 — 自 AutoSwitchBackup 同步 app.py、cdp_lldp_neighbors.py*