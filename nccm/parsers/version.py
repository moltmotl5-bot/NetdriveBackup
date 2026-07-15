from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VersionFields:
    vendor_label: str
    sw_version: str
    models: str
    serials: str


def _join_unique(items: list[str], limit: int = 8) -> str:
    seen: list[str] = []
    for raw in items:
        s = (raw or "").strip()
        if not s or s in seen:
            continue
        seen.append(s)
        if len(seen) >= limit:
            break
    return ", ".join(seen) if seen else "Unknown"


def parse_fortinet(content: str) -> VersionFields:
    vendor = "Fortinet"
    sw_version = "Unknown"
    models_list: list[str] = []
    serials_list: list[str] = []

    match_ver_line = re.search(r"^Version:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
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
            match_fos = re.search(r"FortiOS\s+v?([^\s,]+)", ver_line, re.IGNORECASE)
            if match_fos:
                sw_version = match_fos.group(1)
        match_model = re.search(
            r"(Forti(?:Gate|WiFi|Switch|AP|Analyzer|Manager|Web)-[\w.-]+)",
            ver_line,
            re.IGNORECASE,
        )
        if match_model:
            models_list = [match_model.group(1)]

    serials_list = re.findall(r"Serial-Number:\s*(\S+)", content, re.IGNORECASE)
    if not models_list:
        models_list = re.findall(
            r"(Forti(?:Gate|WiFi|Switch|AP|Analyzer|Manager|Web)-[\w.-]+)",
            content,
            re.IGNORECASE,
        )
    return VersionFields(
        vendor_label=vendor,
        sw_version=sw_version,
        models=_join_unique(models_list),
        serials=_join_unique(serials_list),
    )


def parse_cisco(content: str) -> VersionFields:
    vendor = "Cisco"
    sw_version = "Unknown"
    models_list: list[str] = []
    serials_list: list[str] = []

    is_nxos = "NX-OS" in content or "Cisco Nexus Operating System" in content
    if is_nxos:
        match_ver = re.search(r"NXOS:\s*version\s+([^\s\r\n]+)", content, re.IGNORECASE)
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

    serials_list = re.findall(r"System serial number\s*:\s*([A-Za-z0-9]+)", content, re.IGNORECASE)
    if not serials_list:
        serials_list = re.findall(r"Processor [Bb]oard ID\s+([A-Za-z0-9]+)", content)
    if not models_list:
        models_list = re.findall(r"Model number\s*:\s*(\S+)", content, re.IGNORECASE)
    if not models_list:
        models_list = re.findall(r"cisco\s+([A-Za-z0-9-]+)\s*\(", content, re.IGNORECASE)

    return VersionFields(
        vendor_label=vendor,
        sw_version=sw_version,
        models=_join_unique(models_list),
        serials=_join_unique(serials_list),
    )


def parse_huawei(content: str) -> VersionFields:
    vendor = "Huawei"
    sw_version = "Unknown"
    match_ver = re.search(r"VRP\s*\(R\)\s*software,\s*Version\s+([^\s(]+)", content, re.IGNORECASE)
    if match_ver:
        sw_version = match_ver.group(1)
    else:
        match_ver = re.search(r"Version\s+([^( \r\n]+)", content)
        if match_ver:
            sw_version = match_ver.group(1)

    serials_list = _huawei_serials_from_text(content)
    models_list = _huawei_models_from_text(content)

    return VersionFields(
        vendor_label=vendor,
        sw_version=sw_version,
        models=_join_unique(models_list),
        serials=_join_unique(serials_list),
    )


def _huawei_serials_from_text(content: str) -> list[str]:
    serials_list: list[str] = []
    for m in re.finditer(
        r"^\s*\d+\s+[-\d]+\s+\S+\s+(21\d{10,22})\s",
        content,
        re.MULTILINE,
    ):
        serials_list.append(m.group(1))
    serials_list.extend(
        re.findall(
            r"(?:Serial[- ]?number|BarCode|Device serial number)\s*[:=]\s*(\S+)",
            content,
            re.IGNORECASE,
        )
    )
    if not serials_list:
        serials_list = re.findall(r"BarCode=(\S+)", content)
    if not serials_list:
        serials_list = re.findall(
            r"Equipment serial number\s*:\s*([A-Za-z0-9]+)", content, re.IGNORECASE
        )
    return serials_list


def _huawei_models_from_text(content: str) -> list[str]:
    models_list: list[str] = []
    for m in re.finditer(
        r"^\s*\d+\s+[-\d]+\s+(\S+)\s+21\d+",
        content,
        re.MULTILINE,
    ):
        models_list.append(m.group(1))
    models_list.extend(re.findall(r"Item=(\S+)", content))
    if not models_list:
        models_list = re.findall(r"HUAWEI\s+([A-Za-z0-9-]+)", content, re.IGNORECASE)
    return models_list


def parse_version_info(content: str, vendor_hint: str = "") -> VersionFields:
    text = content or ""
    hint = (vendor_hint or "").lower()

    if hint == "fortinet" or re.search(
        r"FortiOS|FortiGate|FortiWiFi|^Version:\s*Forti",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        return parse_fortinet(text)
    if hint == "huawei" or "VRP (R) software" in text or "Huawei" in text or "elabel" in text:
        return parse_huawei(text)
    if (
        hint == "cisco"
        or "Cisco IOS" in text
        or "Cisco Nexus" in text
        or "NX-OS" in text
    ):
        return parse_cisco(text)

    return VersionFields(
        vendor_label=vendor_hint or "Unknown",
        sw_version="Unknown",
        models="Unknown",
        serials="Unknown",
    )