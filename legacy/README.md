# 舊版 Streamlit NCCM（已封存）

此目錄為 **v3 之前** 的單體應用，僅供對照或遷移參考；**正式部署請用專案根目錄 `README.md` + `docker-compose.yml`**。

| 檔案 | 說明 |
|------|------|
| `app.py` | Streamlit 主程式 |
| `cdp_lldp_neighbors.py` | CDP/LLDP 解析（v3 已遷至 `nccm/parsers/`） |
| `interface_map.py` | Interface Map（v3 已遷至 `nccm/parsers/interface_map.py`） |
| `requirements.txt` | 舊 Python 依賴 |
| `Dockerfile` | 舊 Streamlit 容器映像 |
| `DEMO.csv` | 舊 CSV 範例（v3 請用根目錄 `DEMO-v3.csv`） |
| `docker-deploy-guide.html` | 舊 Docker 圖文指南 |