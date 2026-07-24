#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, IPvAnyAddress


class ProbeRequest(BaseModel):
    ip: IPvAnyAddress = Field(description="Device management IP")
    port: int = Field(22, ge=1, le=65535, description="TCP port to probe")
    timeout: float = Field(3.0, ge=0.5, le=30.0, description="Timeout in seconds")


class ProbeResponse(BaseModel):
    code: str = Field(description="OK or error code")
    msg: str = Field("", description="Detail message")
    ok: bool = Field(False, description="Whether TCP connect succeeded")
    latency_ms: int = Field(0, ge=0, description="Round-trip latency in milliseconds")
