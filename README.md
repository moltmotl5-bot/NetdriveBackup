# AutoSwitchBackup2 — 企業級網路設備 NCCM（精簡部署版）

本目錄為 **AutoSwitchBackup** 專案的**可部署副本**，僅含執行 Streamlit 入口與 CDP/LLDP 鄰居功能所需檔案。

**GitHub：** https://github.com/moltmotl5-bot/AutoSwitchBackup2

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
| `Dockerfile` / `.dockerignore` | 容器映像建置 |
| `.env.example` | 登入帳密範本（複製為 `.env`） |
| `DEMO.csv` | 設備清單格式範例 |
| `docs/docker-deploy-guide.html` | Docker 圖文逐步指南（瀏覽器開啟） |
| `output/` | 備份輸出（執行後寫入，勿 bake 進映像） |

## 快速開始（本機 Python）

```bash
git clone https://github.com/moltmotl5-bot/AutoSwitchBackup2.git
cd AutoSwitchBackup2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 編輯 NCCM_ADMIN_USER / NCCM_ADMIN_PASS
streamlit run app.py
```

瀏覽器：<http://localhost:8501>

## Docker 怎麼用（HOW TO）

> 詳細圖文版：`docs/docker-deploy-guide.html`（`open docs/docker-deploy-guide.html`）

### 1. 建置映像

在**含 `Dockerfile` 的目錄**執行（結尾的 `.` 不可省略）：

```bash
cd AutoSwitchBackup2
docker build -t autoswitchbackup2-nccm:latest .
```

### 2. 執行容器

登入帳密用環境變數；備份資料掛載到 host 的 `output/`：

```bash
docker run -d \
  --name nccm-portal \
  -p 8501:8501 \
  -e NCCM_ADMIN_USER=admin \
  -e NCCM_ADMIN_PASS='請改成強密碼' \
  -v "$(pwd)/output:/app/output" \
  autoswitchbackup2-nccm:latest
```

開啟 <http://localhost:8501>，日誌：`docker logs -f nccm-portal`

### 3. 停止與重建

```bash
docker stop nccm-portal && docker rm nccm-portal
docker build -t autoswitchbackup2-nccm:latest .
```

### 4. 區網搬移映像（不上傳公網）

```bash
docker save autoswitchbackup2-nccm:latest -o autoswitchbackup2-nccm.tar
# 複製到另一台機器後：
docker load -i autoswitchbackup2-nccm.tar
```

### 注意

* 備份目錄須為 `output/<Site>/<IP>_<Hostname>/...`，與 CSV 的 `Site` 一致。
* 容器需能 **SSH** 至交換機網段（批次備份）；僅瀏覽既有備份則只需掛載 `output`。
* **勿**把真實 `.env` 提交 Git 或寫進映像。

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

主專案另含拓撲繪圖、測試腳本等；本 repo **僅維運入口 + Docker 部署**。

## 資安

* 勿將 `.env` 提交至 Git
* SSH 設備帳密僅在備份頁面輸入，不寫入磁碟

## 授權

MIT（與主專案相同）

*最後更新：2026-06-30 — Dockerfile、README Docker 章節*