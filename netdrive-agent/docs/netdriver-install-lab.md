# NetDriver Lab Install (uv, two processes)

**Profile:** local development on macOS — SimuNet + Agent, no Docker.  
**Project:** NetdriverBackup → `netdrive-agent/`  
**Config:** `config/simunet/simunet.lab.yml` (4 simulated devices)

## Prerequisites

| Item | Requirement |
|------|-------------|
| Python | 3.12+ |
| uv | [astral-sh/uv](https://github.com/astral-sh/uv) |
| Working directory | `netdrive-agent/` (monorepo root) |
| Free ports | 8000, 8001, 18020, 18024, 18037, 18038 |

Check ports (optional):

```bash
lsof -i :8000 -i :8001 -i :18020
```

## P1 — Install dependencies (once)

```bash
cd /Users/claw/workspace/NetdriveBackup/netdrive-agent
uv sync
mkdir -p logs
```

## P2 — Environment (lab)

Export before starting both services (same shell or add to your profile for the session):

```bash
export NETDRIVER_SIMUNET_CONFIG=config/simunet/simunet.lab.yml
export NETDRIVER_AGENT_CONFIG=config/agent/agent.yml
```

Or pass `-c` on each command (see below).

## P3 — Run (two terminals)

**Terminal 1 — SimuNet** (HTTP :8001, SSH on lab ports):

```bash
cd /Users/claw/workspace/NetdriveBackup/netdrive-agent
export NETDRIVER_SIMUNET_CONFIG=config/simunet/simunet.lab.yml
uv run simunet --no-reload
```

**Terminal 2 — Agent** (REST :8000):

```bash
cd /Users/claw/workspace/NetdriveBackup/netdrive-agent
export NETDRIVER_AGENT_CONFIG=config/agent/agent.yml
uv run agent --no-reload
```

> Default entrypoints enable `--reload`; use `--no-reload` for stable lab sessions.

## P4 — Verify

| Step | Command / URL |
|------|----------------|
| SimuNet health | `curl -s http://127.0.0.1:8001/health` |
| Agent health | `curl -s http://127.0.0.1:8000/health` |
| API docs | http://127.0.0.1:8000/docs |
| Logs | `tail -f logs/simunet.log` / `logs/agent.log` |

### Example: Cisco Nexus (mock)

Integration tests use these connection fields with `--mock-dev`:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/connect \
  -H 'Content-Type: application/json' \
  -d '{
    "protocol": "ssh",
    "ip": "127.0.0.1",
    "port": 18020,
    "username": "admin",
    "password": "Cisco@123",
    "enable_password": "",
    "vendor": "cisco",
    "model": "nexus",
    "version": "9.6.0",
    "encode": "utf-8",
    "vsys": "default",
    "timeout": 60
  }'
```

Command execution: `POST /api/v1/cmd` with the same connection block plus `commands` (see upstream `docs/quick-start-agent.md`).

### Lab device matrix

| Device | Port | vendor | model | version | Mock password (pytest) |
|--------|------|--------|-------|---------|-------------------------|
| Cisco Nexus | 18020 | cisco | nexus | 9.6.0 | Cisco@123 |
| Cisco ASA | 18024 | cisco | asa | 9.6.0 | r00tme |
| FortiGate | 18037 | fortinet | fortigate | 7.2 | Admin@1234567 |
| Huawei CE | 18038 | huawei | ce | 8.18 | Admin@1234567 |

Passwords follow `tests/integration/conftest.py` for mock mode; SimuNet docs say “any string” — prefer pytest values when API login fails.

## P5 — Optional: integration tests

```bash
cd /Users/claw/workspace/NetdriveBackup/netdrive-agent
export NETDRIVER_SIMUNET_CONFIG=config/simunet/simunet.lab.yml
# Full simunet.yml is used by default in tests unless you align lab ports;
# for full suite use default config or run with upstream simunet.yml devices only.
uv run pytest tests/integration --mock-dev -m integration
```

> Lab yml has fewer devices than integration tests expect; run tests against default `simunet.yml` or extend `simunet.lab.yml` as needed.

## Relation to AutoSwitchBackup2

Parent repo (`../`) remains Netmiko/Streamlit. Use this lab only to prove NetDriver HTTP workflows before any adapter in `app.py`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `config/simunet/simunet.yml` not found | CWD must be `netdrive-agent/` |
| Port in use | Change agent `-p` or remove conflicting device from lab yml |
| Plugin / login errors | Match vendor, model, version to yml; use table passwords |
| Docker later | Set `NETDRIVER_SIMUNET_CONFIG` / `NETDRIVER_AGENT_CONFIG` (not only `NETDRIVER_CONFIG_PATH` from Dockerfiles) |