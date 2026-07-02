import streamlit as st
import pandas as pd
import datetime
import os
import re
import secrets
import time
from dotenv import load_dotenv
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException

# ==========================================
# 0. 載入環境變數與網頁基本設定 (必須在最上方)
# ==========================================
load_dotenv()  # 讀取同目錄下的 .env 檔案

st.set_page_config(page_title="Network Backup Portal", page_icon="🛡️", layout="wide")

_WEAK_PORTAL_PASSWORDS = frozenset({
    "NCCM@2026",
    "password",
    "changeme",
    "admin",
    "your_admin_password",
    "REPLACE_WITH_12CHAR_MIN",
})


def _portal_credential_errors(user: str, password: str) -> list[str]:
    errors: list[str] = []
    if not user:
        errors.append("缺少環境變數 `NCCM_ADMIN_USER`（請設定 .env 或 `--env-file`）。")
    if not password:
        errors.append("缺少環境變數 `NCCM_ADMIN_PASS`。")
    elif len(password) < 12:
        errors.append("`NCCM_ADMIN_PASS` 長度須至少 12 字元。")
    elif password in _WEAK_PORTAL_PASSWORDS:
        errors.append("`NCCM_ADMIN_PASS` 不可使用範例或已知弱密碼。")
    elif password == user:
        errors.append("`NCCM_ADMIN_PASS` 不可與帳號相同。")
    return errors


def _client_ip() -> str:
    try:
        headers = getattr(st.context, "headers", None)
        if headers and hasattr(headers, "get"):
            for key in ("X-Forwarded-For", "X-Real-Ip", "Remote-Addr"):
                val = headers.get(key) or headers.get(key.lower())
                if val:
                    return str(val).split(",")[0].strip()
    except Exception:
        pass
    return "unknown"


def _audit_portal_login(username: str, success: bool) -> None:
    log_path = os.getenv("NCCM_AUDIT_LOG", "nccm_auth.log")
    safe_user = username.replace("\n", "").replace("\r", "")[:128]
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = (
        f"{ts} ip={_client_ip()} user={safe_user!r} "
        f"event=portal_login success={success}\n"
    )
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _load_portal_credentials() -> tuple[str, str]:
    user = (os.getenv("NCCM_ADMIN_USER") or "").strip()
    password = os.getenv("NCCM_ADMIN_PASS") or ""
    errors = _portal_credential_errors(user, password)
    if errors:
        st.error("無法啟動：入口憑證未通過安全檢查")
        for msg in errors:
            st.caption(msg)
        st.stop()
    return user, password


VALID_USER, VALID_PASS = _load_portal_credentials()

# 初始化 session_state 來追蹤登入狀態
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

OUTPUT_DIR = "output"

_FORTINET_DISABLE_PAGING = [
    "config system console",
    "set output standard",
    "end",
]
_FORTINET_TERM_HEIGHT = 9999


def _parse_fortinet_version_info(content: str):
    """Parse get system status / show version style FortiGate output for inventory."""
    vendor = "Fortinet"
    sw_version = "Unknown"
    models_list: list[str] = []
    serials_list: list[str] = []

    match_ver_line = re.search(
        r"^Version:\s*(.+)$",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if match_ver_line:
        ver_line = match_ver_line.group(1).strip()
        match_build = re.search(
            r"\bv(\d+(?:\.\d+)*(?:,build[\d,]+)?(?:\s*\([^)]+\))?)",
            ver_line,
            re.IGNORECASE,
        )
        if match_build:
            sw_version = match_build.group(1)
        else:
            match_fos = re.search(
                r"FortiOS\s+v?([^\s,]+)",
                ver_line,
                re.IGNORECASE,
            )
            if match_fos:
                sw_version = match_fos.group(1)

        match_model = re.search(
            r"(Forti(?:Gate|WiFi|Switch|AP|Analyzer|Manager|Web)-[\w.-]+)",
            ver_line,
            re.IGNORECASE,
        )
        if match_model:
            models_list = [match_model.group(1)]

    serials_list = re.findall(
        r"Serial-Number:\s*(\S+)",
        content,
        re.IGNORECASE,
    )
    if not models_list:
        models_list = re.findall(
            r"(Forti(?:Gate|WiFi|Switch|AP)-[\w-]+)",
            content,
            re.IGNORECASE,
        )
    if not models_list:
        plat = re.search(
            r"Platform Type:\s*(\S+)",
            content,
            re.IGNORECASE,
        )
        if plat:
            models_list = [plat.group(1)]

    return vendor, sw_version, models_list, serials_list


def _fortinet_resize_terminal(net_connect) -> None:
    """Netmiko opens vt100 with height=1000; FortiGate output often stops near ~1001 lines."""
    try:
        conn = getattr(net_connect, "remote_conn", None)
        if conn is not None and hasattr(conn, "resize_pty"):
            conn.resize_pty(width=511, height=_FORTINET_TERM_HEIGHT)
    except Exception:
        pass


def _fortinet_prepare_session(net_connect) -> None:
    _fortinet_resize_terminal(net_connect)
    try:
        net_connect.disable_paging(cmd_verify=False)
    except Exception:
        pass
    try:
        net_connect.send_config_set(
            _FORTINET_DISABLE_PAGING,
            read_timeout=90,
            cmd_verify=False,
        )
    except Exception:
        pass


def _fortinet_fetch_full_configuration(net_connect) -> str:
    """Stream show full-configuration; send space on --More-- until idle."""
    cmd = "show full-configuration"
    net_connect.write_channel(net_connect.normalize_cmd(cmd))
    chunks: list[str] = []
    deadline = time.time() + 900
    idle_rounds = 0
    while time.time() < deadline:
        data = net_connect.read_channel()
        if data:
            idle_rounds = 0
            chunks.append(data)
            compact = data.replace(" ", "").lower()
            if "--more--" in compact or "(more)" in data.lower():
                net_connect.write_channel(" ")
        else:
            idle_rounds += 1
            time.sleep(0.2)
            if idle_rounds >= 20 and chunks:
                break
    raw = "".join(chunks)
    return net_connect._sanitize_output(
        raw,
        strip_command=True,
        command_string=cmd,
        strip_prompt=True,
    )


def _send_fortinet_command(net_connect, cmd_string: str, *, long_output: bool = False) -> str:
    if long_output and cmd_string.strip() == "show full-configuration":
        return _fortinet_fetch_full_configuration(net_connect)
    return net_connect.send_command(cmd_string, read_timeout=120)

NAV_BACKUP = "backup"
NAV_INVENTORY = "inventory"
NAV_NEIGHBORS = "neighbors"
NAV_LABELS = {
    NAV_BACKUP: "🚀 批次備份作業 (Backup Engine)",
    NAV_INVENTORY: "📊 設備總表與版控 (Inventory & Versioning)",
    NAV_NEIGHBORS: "🔗 CDP/LLDP 鄰居 (CDP/LLDP neighbors table)",
}

# ==========================================
# 1. 全域配置與功能函數
# ==========================================
@st.cache_data(ttl=60)
def build_inventory():
    inventory_data = []
    if not os.path.exists(OUTPUT_DIR):
        return pd.DataFrame()

    for site in os.listdir(OUTPUT_DIR):
        site_path = os.path.join(OUTPUT_DIR, site)
        if not os.path.isdir(site_path): continue

        for device_folder in os.listdir(site_path):
            device_path = os.path.join(site_path, device_folder)
            if not os.path.isdir(device_path): continue

            try:
                ip, hostname = device_folder.split('_', 1)
            except ValueError:
                ip, hostname = device_folder, "Unknown"

            dates = sorted(os.listdir(device_path), reverse=True)
            latest_date = dates[0] if dates else None

            sw_version = "Unknown"
            vendor = "Unknown"

            models_list = []
            serials_list = []

            if latest_date:
                version_file = os.path.join(device_path, latest_date, "version_info.txt")
                if os.path.exists(version_file):
                    with open(version_file, "r", encoding="utf-8") as f:
                        content = f.read()

                        if (
                            "Cisco IOS Software" in content
                            or "Cisco Nexus" in content
                            or "NX-OS" in content
                        ):
                            vendor = "Cisco"
                            is_nxos = (
                                "NX-OS" in content
                                or "Cisco Nexus Operating System" in content
                            )

                            if is_nxos:
                                match_ver = re.search(
                                    r"NXOS:\s*version\s+([^\s\r\n]+)",
                                    content,
                                    re.IGNORECASE,
                                )
                                if match_ver:
                                    sw_version = match_ver.group(1)

                                nexus_models = re.findall(
                                    r"^\s*cisco\s+(Nexus\S+(?:\s+[A-Za-z0-9.-]+)?)\s*\(",
                                    content,
                                    re.MULTILINE | re.IGNORECASE,
                                )
                                if nexus_models:
                                    models_list = [m.strip() for m in nexus_models]
                            else:
                                match_ver = re.search(r"Version\s+([^\s,]+)", content)
                                if match_ver:
                                    sw_version = match_ver.group(1)

                            serials_list = re.findall(
                                r"System serial number\s*:\s*([A-Za-z0-9]+)",
                                content,
                                re.IGNORECASE,
                            )
                            if not serials_list:
                                serials_list = re.findall(
                                    r"Processor [Bb]oard ID\s+([A-Za-z0-9]+)",
                                    content,
                                )

                            if not models_list:
                                models_list = re.findall(
                                    r"Model number\s*:\s*(\S+)", content, re.IGNORECASE
                                )
                            if not models_list:
                                models_list = re.findall(
                                    r"cisco\s+([A-Za-z0-9-]+)\s*\(",
                                    content,
                                    re.IGNORECASE,
                                )

                        elif re.search(
                            r"FortiOS|FortiGate|FortiWiFi|FortiSwitch|^Version:\s*Forti",
                            content,
                            re.MULTILINE | re.IGNORECASE,
                        ):
                            vendor, sw_version, models_list, serials_list = (
                                _parse_fortinet_version_info(content)
                            )

                        elif (
                            "Cisco Controller" in content
                            or (
                                "Product Name" in content
                                and "Wireless" in content
                            )
                        ):
                            vendor = "Cisco"
                            match_ver = re.search(
                                r"Product Version\.{2,}\s*([^\r\n]+)",
                                content,
                            )
                            if match_ver:
                                sw_version = match_ver.group(1).strip()
                            else:
                                match_ver = re.search(
                                    r"Version\.{2,}\s*([^\r\n]+)",
                                    content,
                                )
                                if match_ver:
                                    sw_version = match_ver.group(1).strip()
                            serials_list = re.findall(
                                r"Serial Number\.{2,}\s*([A-Za-z0-9]+)",
                                content,
                            )
                            models_list = re.findall(
                                r"Product Name\.{2,}\s*([^\r\n]+)",
                                content,
                            )
                            if models_list:
                                models_list = [m.strip() for m in models_list]

                        elif "VRP (R) software" in content and (
                            "AC6605" in content
                            or "AC6005" in content
                            or "AC6800" in content
                            or "WLAN" in content
                            or "AirEngine" in content
                        ):
                            vendor = "Huawei"
                            match_ver = re.search(
                                r"VRP\s*\(R\)\s*software,\s*Version\s+([^\s(]+)",
                                content,
                                re.IGNORECASE,
                            )
                            if match_ver:
                                sw_version = match_ver.group(1)
                            serials_list = re.findall(
                                r"(?:ESN|BarCode)[:=](\S+)",
                                content,
                                re.IGNORECASE,
                            )
                            models_list = re.findall(
                                r"(?:AC\d{4}|AirEngine[\w-]+)",
                                content,
                            )

                        elif "VRP (R) software" in content or "Huawei" in content or "elabel" in content:
                            vendor = "Huawei"
                            match_ver = re.search(r'Version\s+([^(\s]+)', content)
                            if match_ver: sw_version = match_ver.group(1)
                            else: sw_version = "VRP extracted"

                            serials_list = re.findall(r'BarCode=(\S+)', content)
                            if not serials_list:
                                serials_list = re.findall(r'Equipment serial number\s*:\s*([A-Za-z0-9]+)', content, re.IGNORECASE)

                            models_list = re.findall(r'Item=(\S+)', content)
                            if not models_list:
                                models_list = re.findall(r'HUAWEI\s+([A-Za-z0-9-]+)', content)

            max_devices = max(len(models_list), len(serials_list))

            if max_devices == 0:
                inventory_data.append({
                    "Site": site, "Vendor": vendor, "Model": "Unknown",
                    "IP": ip, "Hostname": hostname, "Software Version": sw_version,
                    "Serial Number": "Unknown", "Path": device_path
                })
            else:
                for i in range(max_devices):
                    m = models_list[i].strip() if i < len(models_list) else "Unknown"
                    sn = serials_list[i].strip() if i < len(serials_list) else "Unknown"

                    inventory_data.append({
                        "Site": site, "Vendor": vendor, "Model": m,
                        "IP": ip, "Hostname": hostname, "Software Version": sw_version,
                        "Serial Number": sn, "Path": device_path
                    })

    return pd.DataFrame(inventory_data)


@st.cache_data(ttl=60)
def load_neighbor_catalog_cached():
    from cdp_lldp_neighbors import build_neighbor_catalog

    return build_neighbor_catalog(OUTPUT_DIR)


# ==========================================
# 2. 登入介面邏輯
# ==========================================
if not st.session_state["logged_in"]:
    st.title("🔒 NCCM 系統登入")
    st.markdown("這是一個受保護的企業級資產與設定檔管理系統，請輸入您的管理員憑證。")

    with st.form("login_form"):
        input_user = st.text_input("管理員帳號")
        input_pwd = st.text_input("登入密碼", type="password")
        submit_btn = st.form_submit_button("登入系統", type="primary")

        if submit_btn:
            entered_user = input_user.strip()
            user_ok = secrets.compare_digest(
                entered_user.encode("utf-8"),
                VALID_USER.encode("utf-8"),
            )
            pass_ok = secrets.compare_digest(
                input_pwd.encode("utf-8"),
                VALID_PASS.encode("utf-8"),
            )
            if user_ok and pass_ok:
                _audit_portal_login(entered_user, True)
                st.session_state["logged_in"] = True
                st.success("登入成功！正在載入系統...")
                st.rerun()
            else:
                _audit_portal_login(entered_user, False)
                st.error("❌ 帳號或密碼錯誤，請重新輸入。")

# ==========================================
# 3. 系統主畫面邏輯 (僅在登入後顯示)
# ==========================================
else:
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = NAV_BACKUP

    with st.sidebar:
        st.markdown(f"👤 **登入身分:** `{VALID_USER}`")
        st.divider()
        st.markdown("**功能選單**")
        if st.button(
            NAV_LABELS[NAV_BACKUP],
            width="stretch",
            type="primary" if st.session_state["nav_page"] == NAV_BACKUP else "secondary",
            key="nav_btn_backup",
        ):
            st.session_state["nav_page"] = NAV_BACKUP
            st.rerun()
        if st.button(
            NAV_LABELS[NAV_INVENTORY],
            width="stretch",
            type="primary" if st.session_state["nav_page"] == NAV_INVENTORY else "secondary",
            key="nav_btn_inventory",
        ):
            st.session_state["nav_page"] = NAV_INVENTORY
            st.rerun()
        if st.button(
            NAV_LABELS[NAV_NEIGHBORS],
            width="stretch",
            type="primary" if st.session_state["nav_page"] == NAV_NEIGHBORS else "secondary",
            key="nav_btn_neighbors",
        ):
            st.session_state["nav_page"] = NAV_NEIGHBORS
            st.rerun()
        st.divider()
        if st.button("🚪 登出系統", width="stretch"):
            st.session_state["logged_in"] = False
            st.rerun()

    nav_page = st.session_state["nav_page"]
    st.title("🛡️ 企業級網路設備 NCCM 平台")
    st.subheader(NAV_LABELS.get(nav_page, NAV_LABELS[NAV_BACKUP]))

    # ==========================================
    # 批次備份作業
    # ==========================================
    if nav_page == NAV_BACKUP:
        st.markdown("上傳您的 `Site, IP, Vendor` CSV 清單，系統將自動連線並將設定檔與拓撲資訊分類歸檔。")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("1. 設備認證資訊")
            username = st.text_input("全域 SSH 帳號", placeholder="輸入網路設備 admin 帳號")
            password = st.text_input("全域 SSH 密碼", type="password", placeholder="輸入網路設備密碼")

        with col2:
            st.subheader("2. 上傳設備清單")
            uploaded_file = st.file_uploader("上傳 devices.csv 檔案", type=["csv"])

        st.divider()

        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            required_columns = ['Site', 'IP', 'Vendor']

            if not all(col in df.columns for col in required_columns):
                st.error(f"上傳失敗！CSV 必須包含這三個欄位：{', '.join(required_columns)}")
            else:
                st.success(f"成功讀取檔案！共發現 **{len(df)}** 台設備。")
                with st.expander("👀 點擊預覽設備清單", expanded=False):
                    st.dataframe(df, width="stretch", height=200)

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    start_backup_btn = st.button("🚀 開始執行全自動備份", type="primary", width="stretch")
                with col_btn2:
                    stop_backup_btn = st.button("🛑 緊急停止 (強制中斷)", type="secondary", width="stretch")

                if stop_backup_btn:
                    st.error("🛑 備份作業已由使用者手動強制中斷！請重新整理頁面或重新執行。")
                    st.stop()

                if start_backup_btn:
                    if not username or not password:
                        st.warning("⚠️ 請先輸入 SSH 帳號與密碼！")
                    else:
                        total_devices = len(df)
                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        success_list = []
                        failed_list = []
                        auth_fail_count = 0

                        st.markdown("### 📝 即時執行日誌")
                        log_container = st.container(height=300)
                        log_placeholder = log_container.empty()
                        live_logs = []

                        def update_logs(message):
                            time_str = datetime.datetime.now().strftime("%H:%M:%S")
                            live_logs.append(f"[{time_str}] {message}")
                            if len(live_logs) > 500:
                                live_logs.pop(0)
                            log_placeholder.code("\\n".join(live_logs), language="bash")

                        for index, row in df.iterrows():
                            site = str(row['Site']).strip()
                            target_ip = str(row['IP']).strip()
                            vendor = str(row['Vendor']).strip().lower()

                            current_count = index + 1
                            status_text.info(f"⏳ 正在處理: [{site}] {target_ip} ({vendor}) ... ({current_count}/{total_devices})")
                            update_logs(f"開始嘗試連線至 {target_ip} ({vendor})...")

                            if vendor == 'cisco':
                                device_type = 'cisco_ios'
                                commands = {
                                    'config': 'show running-config', 'interfaces': 'show interface status',
                                    'version_info': 'show version', 'cdp': 'show cdp neighbors', 'lldp': 'show lldp neighbors'
                                }
                            elif vendor == 'huawei':
                                device_type = 'huawei'
                                commands = {
                                    'config': 'display current-configuration', 'interfaces': 'display interface brief',
                                    'version_info': 'display elabel', 'cdp': 'display cdp neighbor', 'lldp': 'display lldp neighbor brief'
                                }
                            elif vendor == 'fortinet':
                                device_type = 'fortinet'
                                commands = {
                                    'config': 'show full-configuration',
                                    'version_info': 'get system status',
                                    'interfaces': 'get system interface physical',
                                }
                            elif vendor in ('cisco_wlc', 'cisco-wlc'):
                                device_type = 'cisco_wlc'
                                commands = {
                                    'config': 'show running-config',
                                    'version_info': 'show sysinfo',
                                    'interfaces': 'show interface summary',
                                    'cdp': 'show cdp neighbors',
                                    'lldp': 'show lldp neighbors',
                                }
                            elif vendor in ('huawei_wlc', 'huawei-wlc'):
                                device_type = 'huawei'
                                commands = {
                                    'config': 'display current-configuration',
                                    'version_info': 'display version',
                                    'interfaces': 'display interface brief',
                                    'lldp': 'display lldp neighbor brief',
                                }
                            else:
                                failed_list.append({'Site': site, 'IP': target_ip, 'Reason': f"未知的廠牌: {vendor}"})
                                update_logs(f"❌ 錯誤: {target_ip} 未知的廠牌設定")
                                progress_bar.progress(current_count / total_devices)
                                continue

                            netmiko_device = {
                                'device_type': device_type, 'host': target_ip,
                                'username': username, 'password': password,
                                'timeout': 10, 'auth_timeout': 10
                            }

                            try:
                                with ConnectHandler(**netmiko_device) as net_connect:
                                    raw_prompt = net_connect.find_prompt()
                                    hostname = raw_prompt.replace('#', '').replace('>', '').replace('[', '').replace(']', '').strip()

                                    master_folder = "output"
                                    base_folder = f"{target_ip}_{hostname}"
                                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
                                    backup_folder = os.path.join(master_folder, site, base_folder, timestamp)

                                    if not os.path.exists(backup_folder):
                                        os.makedirs(backup_folder)

                                    if vendor == 'fortinet':
                                        _fortinet_prepare_session(net_connect)

                                    for cmd_type, cmd_string in commands.items():
                                        if vendor == 'fortinet':
                                            output_result = _send_fortinet_command(
                                                net_connect,
                                                cmd_string,
                                                long_output=(cmd_type == 'config'),
                                            )
                                            if cmd_type == 'config':
                                                line_count = output_result.count("\n") + (1 if output_result else 0)
                                                update_logs(
                                                    f"ℹ️ {target_ip} FortiGate config.txt 約 {line_count} 行"
                                                )
                                        else:
                                            output_result = net_connect.send_command(cmd_string)
                                        file_name = os.path.join(backup_folder, f"{cmd_type}.txt")
                                        with open(file_name, "w", encoding="utf-8") as f:
                                            f.write(output_result)

                                    success_list.append({'Site': site, 'IP': target_ip, 'Hostname': hostname, 'Status': '✅ 成功'})
                                    update_logs(f"✅ 成功: {hostname} ({target_ip}) 備份完成！")

                                    auth_fail_count = 0

                            except NetmikoAuthenticationException:
                                failed_list.append({'Site': site, 'IP': target_ip, 'Reason': "認證失敗"})
                                update_logs(f"❌ 錯誤: {target_ip} 帳號密碼認證失敗")
                                auth_fail_count += 1

                                if auth_fail_count >= 3:
                                    update_logs("🚨 連續 3 台設備認證失敗！懷疑全域密碼輸入錯誤，系統自動中止任務。")
                                    st.error("🚨 偵測到連續密碼錯誤，為節省等待時間，備份已自動強制中斷，請檢查密碼！")
                                    break

                            except NetmikoTimeoutException:
                                failed_list.append({'Site': site, 'IP': target_ip, 'Reason': "連線逾時"})
                                update_logs(f"❌ 錯誤: {target_ip} 連線逾時")
                            except Exception as e:
                                error_msg = str(e).split('\\n')[0]
                                failed_list.append({'Site': site, 'IP': target_ip, 'Reason': error_msg})
                                update_logs(f"❌ 錯誤: {target_ip} 未預期異常 ({error_msg})")

                            progress_bar.progress(current_count / total_devices)

                        build_inventory.clear()

                        if auth_fail_count >= 3:
                            status_text.error(f"🛑 任務中止。共執行了 {current_count} 台。")
                        else:
                            status_text.success(f"🎉 備份完成！成功: {len(success_list)} 台，失敗: {len(failed_list)} 台")

    # ==========================================
    # 設備總表與版控
    # ==========================================
    elif nav_page == NAV_INVENTORY:
        st.markdown("瀏覽所有備份的設備資訊與版本控制。")

        if not os.path.exists(OUTPUT_DIR):
            st.warning("⚠️ `output` 資料夾不存在。請先執行備份任務產生資料！")
        else:
            df = build_inventory()
            if df.empty:
                st.info("📭 暫無設備資料。請先執行備份任務。")
            else:
                # 搜尋與過濾
                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    search_term = st.text_input("🔍 搜尋設備 (IP/Hostname/Model)", placeholder="輸入關鍵字...")
                with col2:
                    site_filter = st.selectbox("📍 篩選 Site", ["全部"] + sorted(df['Site'].unique().tolist()))
                with col3:
                    vendor_filter = st.selectbox("🏭 篩選廠牌", ["全部"] + sorted(df['Vendor'].unique().tolist()))

                # 套用過濾
                filtered_df = df.copy()
                if search_term:
                    mask = (
                        filtered_df['IP'].str.contains(search_term, case=False, na=False) |
                        filtered_df['Hostname'].str.contains(search_term, case=False, na=False) |
                        filtered_df['Model'].str.contains(search_term, case=False, na=False)
                    )
                    filtered_df = filtered_df[mask]
                if site_filter != "全部":
                    filtered_df = filtered_df[filtered_df['Site'] == site_filter]
                if vendor_filter != "全部":
                    filtered_df = filtered_df[filtered_df['Vendor'] == vendor_filter]

                filtered_df = filtered_df.reset_index(drop=True)
                display_df = filtered_df.drop(columns=["Path"])

                table_event = st.dataframe(
                    display_df,
                    column_config={
                        "Site": "Site",
                        "Vendor": "廠牌",
                        "Model": "型號",
                        "IP": "IP 位址",
                        "Hostname": "主機名稱",
                        "Software Version": "軟體版本",
                        "Serial Number": "序列號",
                    },
                    hide_index=True,
                    width="stretch",
                    on_select="rerun",
                    selection_mode="single-row",
                    key="inventory_table",
                )

                st.caption(f"顯示 {len(filtered_df)} 筆記錄（總共 {len(df)} 筆）· 點選一列以查看 Running-Configuration 與版控")

                selected_rows = []
                if table_event is not None and getattr(table_event, "selection", None):
                    selected_rows = list(table_event.selection.rows or [])

                if selected_rows:
                    row_idx = selected_rows[0]
                    if 0 <= row_idx < len(filtered_df):
                        row = filtered_df.iloc[row_idx]
                        device_path = row["Path"]
                        device_label = f"{row['Hostname']} ({row['IP']})"

                        st.divider()
                        st.subheader(f"📂 Running-Configuration 與版控 — {device_label}")

                        if not os.path.isdir(device_path):
                            st.warning("找不到該設備的備份目錄。")
                        else:
                            backup_dirs = sorted(
                                [
                                    d
                                    for d in os.listdir(device_path)
                                    if os.path.isdir(os.path.join(device_path, d))
                                ],
                                reverse=True,
                            )[:10]

                            if not backup_dirs:
                                st.info("此設備尚無已備份的設定檔版本。")
                            else:
                                selected_ts = st.selectbox(
                                    "選擇備份版本（時間戳記）",
                                    backup_dirs,
                                    key=f"inv_version_{device_path}",
                                )
                                config_path = os.path.join(device_path, selected_ts, "config.txt")

                                if not os.path.isfile(config_path):
                                    st.warning(f"此版本沒有 `config.txt`（{selected_ts}）。")
                                else:
                                    with open(config_path, "r", encoding="utf-8", errors="replace") as f:
                                        config_text = f.read()

                                    st.markdown(f"**版本：** `{selected_ts}`")
                                    st.code(config_text, language="text")
                                    st.download_button(
                                        label="⬇️ 下載此版本 config.txt",
                                        data=config_text,
                                        file_name=f"{row['IP']}_{row['Hostname']}_{selected_ts}_config.txt",
                                        mime="text/plain",
                                        width="content",
                                    )

    # ==========================================
    # CDP/LLDP 鄰居表
    # ==========================================
    elif nav_page == NAV_NEIGHBORS:
        from cdp_lldp_neighbors import make_device_key

        st.markdown(
            "瀏覽設備 CDP/LLDP 鄰居；操作方式與 **設備總表與版控** 相同："
            "搜尋／篩選後**點選上方設備表格一列**，下方顯示介面鄰居表。"
        )

        if not os.path.exists(OUTPUT_DIR):
            st.warning("⚠️ `output` 資料夾不存在。請先執行備份任務產生資料！")
        else:
            df = build_inventory()
            cat_df, _hostname_lookup, neighbors_by_key = load_neighbor_catalog_cached()

            if df.empty:
                st.info("📭 暫無設備資料。請先執行備份任務。")
            else:
                df["device_key"] = df.apply(
                    lambda r: make_device_key(r["Site"], r["IP"], r["Hostname"]), axis=1
                )
                if not cat_df.empty:
                    meta = cat_df.set_index("device_key")[
                        ["neighbor_count", "cdp_status", "lldp_status"]
                    ]
                    df = df.join(meta, on="device_key", how="left")
                df["neighbor_count"] = df["neighbor_count"].fillna(0).astype(int)
                df["cdp_status"] = df["cdp_status"].fillna("missing")
                df["lldp_status"] = df["lldp_status"].fillna("missing")

                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    search_term = st.text_input(
                        "🔍 搜尋設備 (IP/Hostname/Model)",
                        placeholder="輸入關鍵字...",
                    )
                with col2:
                    site_filter = st.selectbox(
                        "📍 篩選 Site",
                        ["全部"] + sorted(df["Site"].unique().tolist()),
                    )
                with col3:
                    vendor_filter = st.selectbox(
                        "🏭 篩選廠牌",
                        ["全部"] + sorted(df["Vendor"].unique().tolist()),
                    )

                filtered_df = df.copy()
                if search_term:
                    mask = (
                        filtered_df["IP"].str.contains(search_term, case=False, na=False)
                        | filtered_df["Hostname"].str.contains(search_term, case=False, na=False)
                        | filtered_df["Model"].str.contains(search_term, case=False, na=False)
                    )
                    filtered_df = filtered_df[mask]
                if site_filter != "全部":
                    filtered_df = filtered_df[filtered_df["Site"] == site_filter]
                if vendor_filter != "全部":
                    filtered_df = filtered_df[filtered_df["Vendor"] == vendor_filter]

                filtered_df = filtered_df.reset_index(drop=True)
                display_df = filtered_df.drop(columns=["Path", "device_key"], errors="ignore")

                device_table_event = st.dataframe(
                    display_df,
                    column_config={
                        "Site": "Site",
                        "Vendor": "廠牌",
                        "Model": "型號",
                        "IP": "IP 位址",
                        "Hostname": "主機名稱",
                        "Software Version": "軟體版本",
                        "Serial Number": "序列號",
                        "neighbor_count": "鄰居數",
                        "cdp_status": "CDP",
                        "lldp_status": "LLDP",
                    },
                    hide_index=True,
                    width="stretch",
                    on_select="rerun",
                    selection_mode="single-row",
                    key="neighbors_device_table",
                )

                st.caption(
                    f"顯示 {len(filtered_df)} 筆記錄（總共 {len(df)} 筆）· "
                    "點選一列以查看 CDP/LLDP 介面鄰居"
                )

                selected_device_key = st.session_state.get("neighbors_device_key")
                device_selected_rows = []
                if device_table_event is not None and getattr(device_table_event, "selection", None):
                    device_selected_rows = list(device_table_event.selection.rows or [])

                if device_selected_rows:
                    row_idx = device_selected_rows[0]
                    if 0 <= row_idx < len(filtered_df):
                        selected_device_key = filtered_df.iloc[row_idx]["device_key"]
                        st.session_state["neighbors_device_key"] = selected_device_key

                if selected_device_key and selected_device_key in df["device_key"].values:
                    row = df[df["device_key"] == selected_device_key].iloc[0]
                    device_label = f"{row['Hostname']} ({row['IP']})"
                    neighbor_rows = neighbors_by_key.get(selected_device_key, [])

                    st.divider()
                    st.subheader(f"🔗 CDP/LLDP 介面鄰居 — {device_label}")

                    if row.get("cdp_status") == "error":
                        st.warning(
                            "此設備最新 `cdp.txt` 為指令錯誤或無效輸出（可能需改用 `show cdp neighbors`）。"
                        )
                    if row.get("lldp_status") == "error":
                        st.warning("此設備最新 `lldp.txt` 為指令錯誤或無效輸出。")

                    if str(row.get("Vendor", "")).lower() == "cisco" and row.get("cdp_status") == "ok":
                        st.caption("Cisco 設備且 CDP 解析成功：僅顯示 CDP，不列入 LLDP。")

                    st.caption(
                        f"共 **{len(neighbor_rows)}** 筆鄰居（最新備份 · "
                        f"CDP:{row.get('cdp_status')} · LLDP:{row.get('lldp_status')}）"
                    )

                    if not neighbor_rows:
                        st.info("此設備沒有解析到 CDP/LLDP 鄰居。")
                    else:
                        nb_df = pd.DataFrame(neighbor_rows)
                        inv_by_key = df.set_index("device_key")[["Hostname", "IP"]]

                        def _neighbor_device_label(remote_key, remote_hostname: str) -> str:
                            if remote_key and remote_key in inv_by_key.index:
                                inv = inv_by_key.loc[remote_key]
                                return f"{inv['Hostname']} ({inv['IP']})"
                            return remote_hostname

                        nb_display = pd.DataFrame(
                            {
                                "本端介面": nb_df["local_interface"],
                                "協定": nb_df["protocol"],
                                "鄰居設備": nb_df.apply(
                                    lambda r: _neighbor_device_label(
                                        r.get("remote_device_key"), r["remote_hostname"]
                                    ),
                                    axis=1,
                                ),
                                "鄰居介面": nb_df["remote_port"],
                                "連線類型": nb_df["cable_type"],
                            }
                        )

                        st.dataframe(
                            nb_display,
                            hide_index=True,
                            width="stretch",
                            key="neighbors_neighbor_table",
                        )
