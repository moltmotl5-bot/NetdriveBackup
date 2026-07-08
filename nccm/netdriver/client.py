from __future__ import annotations

from typing import Any

import httpx

from nccm.config import netdriver_url
from nccm.models import NetDriverProfile


class NetDriverError(RuntimeError):
    pass


class NetDriverClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0):
        self.base_url = (base_url or netdriver_url()).rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=5.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def connect(
        self,
        *,
        ip: str,
        port: int,
        username: str,
        password: str,
        profile: NetDriverProfile,
        enable_password: str = "",
        timeout: int = 60,
    ) -> dict[str, Any]:
        body = {
            "protocol": "ssh",
            "ip": ip,
            "port": port,
            "username": username,
            "password": password,
            "enable_password": enable_password if enable_password is not None else "",
            "vendor": profile.vendor,
            "model": profile.model,
            "version": profile.version,
            "encode": "utf-8",
            "vsys": "default",
            "timeout": timeout,
        }
        r = httpx.post(
            f"{self.base_url}/api/v1/connect",
            json=body,
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise NetDriverError(f"connect HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        if data.get("code") != "OK":
            raise NetDriverError(data.get("msg") or data.get("code") or "connect failed")
        return data

    def cmd(
        self,
        *,
        ip: str,
        port: int,
        username: str,
        password: str,
        profile: NetDriverProfile,
        command: str,
        mode: str = "enable",
        enable_password: str = "",
        timeout: int = 120,
    ) -> str:
        body = {
            "protocol": "ssh",
            "ip": ip,
            "port": port,
            "username": username,
            "password": password,
            "enable_password": enable_password if enable_password is not None else "",
            "vendor": profile.vendor,
            "model": profile.model,
            "version": profile.version,
            "encode": "utf-8",
            "vsys": "default",
            "timeout": timeout,
            "continue_on_error": False,
            "commands": [
                {
                    "type": "raw",
                    "mode": mode,
                    "command": command,
                    "template": "",
                    "detail_output": True,
                }
            ],
        }
        r = httpx.post(
            f"{self.base_url}/api/v1/cmd",
            json=body,
            timeout=max(self.timeout, float(timeout) + 10),
        )
        if r.status_code >= 400:
            raise NetDriverError(f"cmd HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        if data.get("code") != "OK":
            raise NetDriverError(data.get("msg") or data.get("code") or "cmd failed")
        output = data.get("output")
        if output is not None:
            return str(output)
        result = data.get("result") or []
        if result and result[0].get("ret") is not None:
            return str(result[0]["ret"])
        return ""

    def disconnect(
        self,
        *,
        ip: str,
        port: int,
        username: str,
        password: str,
        profile: NetDriverProfile,
    ) -> None:
        body = {
            "protocol": "ssh",
            "ip": ip,
            "port": port,
            "username": username,
            "password": password,
            "vendor": profile.vendor,
            "model": profile.model,
            "version": profile.version,
            "encode": "utf-8",
            "vsys": "default",
            "timeout": 30,
        }
        try:
            httpx.post(
                f"{self.base_url}/api/v1/disconnect",
                json=body,
                timeout=15.0,
            )
        except httpx.HTTPError:
            pass