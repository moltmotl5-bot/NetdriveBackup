from __future__ import annotations

from nccm.discovery.cisco import classify_cisco_show_version
from nccm.discovery.fortinet import classify_fortinet_status
from nccm.discovery.huawei import classify_huawei_display_version
from nccm.models import NetDriverProfile
from nccm.profiles import normalize_vendor


def classify_from_version_output(vendor: str, text: str) -> NetDriverProfile | None:
    v = normalize_vendor(vendor)
    if v == "cisco":
        return classify_cisco_show_version(text)
    if v == "fortinet":
        return classify_fortinet_status(text)
    if v == "huawei":
        return classify_huawei_display_version(text)
    return None