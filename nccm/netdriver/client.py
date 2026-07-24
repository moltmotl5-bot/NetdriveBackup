from __future__ import annotations

from typing import Any

import httpx

from nccm.config import netdriver_url
from nccm.models import NetDriverProfile
from nccm.profiles import normalize_profile_for_agent, normalize_vendor


class NetDriverError(RuntimeError):
    pass


class NetDriverClient:
    @staticmethod
    def command_entry(*, vendor: str, agent_mode: str, command: str) -> dict:
        """Build one /api/v1/cmd command object — field name differs by vendor plugin."""
        entry: dict = {
            "type": "raw",
            "command": command,
            "template": "",
            "detail_output": True,
        }
        v = normalize_vendor(vendor)
        if v == "cisco":
            entry["login"] = agent_mode
        else:
            entry["mode"] = agent_mode
        return entry

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
        profile = normalize_profile_for_agent(profile)
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
        agent_mode: str,
        enable_password: str = "",
        timeout: int = 120,
    ) -> str:
        profile = normalize_profile_for_agent(profile)
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
                self.command_entry(
                    vendor=profile.vendor,
                    agent_mode=agent_mode,
                    command=command,
                )
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
            msg = (data.get("msg") or "").strip() or str(data.get("code") or "cmd failed")
            out = data.get("output")
            if isinstance(out, str) and out.strip():
                tail = "\n".join(out.strip().splitlines()[-8:])
                msg = f"{msg} | CLI tail: {tail[:800]}"
            raise NetDriverError(msg)
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
        profile = normalize_profile_for_agent(profile)
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

    def probe(self, *, ip: str, port: int = 22, timeout: float = 3.0) -> dict[str, Any]:
        body = {"ip": ip, "port": int(port), "timeout": float(timeout)}
        r = httpx.post(
            f"{self.base_url}/api/v1/probe",
            json=body,
            timeout=max(5.0, float(timeout) + 2.0),
        )
        if r.status_code >= 400:
            raise NetDriverError(f"probe HTTP {r.status_code}: {r.text[:500]}")
        return r.json()