#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import time

from netdriver_agent.models.probe import ProbeRequest, ProbeResponse


class ProbeRequestHandler:
    async def handle(self, request: ProbeRequest) -> ProbeResponse:
        if not request:
            raise ValueError("ProbeRequest is empty")
        ip = str(request.ip)
        port = int(request.port)
        timeout = float(request.timeout)
        started = time.monotonic()
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            latency_ms = int((time.monotonic() - started) * 1000)
            return ProbeResponse(code="OK", msg="", ok=True, latency_ms=latency_ms)
        except Exception as exc:  # noqa: BLE001 — return probe failure to caller
            return ProbeResponse(
                code="PROBE_FAILED",
                msg=str(exc)[:500],
                ok=False,
                latency_ms=0,
            )
