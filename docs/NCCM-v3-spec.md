# NCCM v3 (NetdriverBackup)

Greenfield network configuration backup portal. **NetDriver Agent** replaces Netmiko. **No WLC** support.

## Stack

| Layer | Choice |
|-------|--------|
| UI | **FastAPI + Jinja2 + HTMX** (dark NOC layout) |
| Core | Python package `nccm` |
| Transport | HTTP → NetDriver Agent (`NCCM_NETDRIVER_URL`, default `http://127.0.0.1:8000`) |
| Lab | `netdrive-agent` SimuNet (`simunet.lab.yml`) — dev only |
| Legacy | `app.py` / `output/` — **not read** by v3 |

## Supported vendors

- `cisco` — optional CSV Model/Version; **auto-discovery** via `show version` when omitted
- `huawei` — optional Model/Version; default probe `ce` / `8.0`
- `fortinet` — `fortigate` / `7.2` default probe

Rejected at import: `cisco_wlc`, `huawei_wlc`, `wlc`, `aireos`.

## CSV schema

Required: `Site`, `IP`, `Vendor`

Optional: `Model`, `Version`, `Hostname` (hint only), `Port` (default 22)

Example: `DEMO-v3.csv`

## Storage layout (`NCCM_STORE_DIR`, default `./store`)

```
store/
  index.db                 # SQLite inventory index (Phase 3)
  runs/{run_id}/run.log
  {site}/{ip}__{hostname}/snapshots/{iso8601}/
    manifest.json
    config.txt
    version_info.txt
    interfaces.txt         # optional
    cdp.txt / lldp.txt     # optional
```

### manifest.json

- `run_id`, `site`, `ip`, `hostname`, `vendor`
- `netdriver`: `{vendor, model, version, discovery}` (`discovery`: `csv` | `auto` | `failed`)
- `artifacts`: `[{name, path, lines}]`
- `status`: `ok` | `failed`
- `error`: optional string

## Cisco discovery (no CSV model)

1. Connect with probe profile: `catalyst` + version `17.0` (or user CSV if present).
2. `show version` in **login** mode (no `enable`).
3. Classify → `nexus` | `catalyst` | `isr` | `asr` | `asa`.
4. Reconnect if model/version differ from probe.
5. Run backup command set from `nccm.profiles` (Cisco: all commands `login`; **nexus** config `show running-config`, **IOS** models `show running-config view full`; Agent Cisco plugin skips `enable` CLI).

## UI pages (parity with AutoSwitchBackup2)

| Route | Legacy nav |
|-------|------------|
| `/backup` | 批次備份 |
| `/inventory` | 設備總表與版控 |
| `/neighbors` | CDP/LLDP |
| `/interfaces` | Interface Map |

Auth: `NCCM_ADMIN_USER` / `NCCM_ADMIN_PASS` (min 12 chars), session cookie.

REST API: API tokens in `portal_auth.db` (admin **API Token** page + embedded HTML manual); clients send `X-API-Key` on `GET /api/v1/inventory`. No `API_KEY` in `.env`.

## Run

```bash
# Terminal 1 — SimuNet lab (optional)
cd netdrive-agent && NETDRIVER_SIMUNET_CONFIG=config/simunet/simunet.lab.yml uv run simunet --no-reload

# Terminal 2 — Agent
cd netdrive-agent && uv run agent --no-reload

# Terminal 3 — CLI backup
pip install -r requirements-v3.txt
export NCCM_NETDRIVER_URL=http://127.0.0.1:8000
python -m nccm backup --csv DEMO-v3.csv --user admin --password '***'

# Rebuild inventory index from store/
python -m nccm index rebuild

# Terminal 3 — Web UI
uvicorn web.main:app --reload --port 8501
```

## Phases

1. **Done (skeleton)**: `nccm` client, backup runner, manifest, CLI, FastAPI shell + backup form
2. **Done**: Inventory + SQLite (`store/index.db`) + version parsers + `/inventory` HTMX UI
3. **Done**: Neighbors + Interface Map (`nccm.parsers.cdp_lldp`, `interface_map`) + Web UI
4. **Done**: Backup background jobs + SSE live log (`/backup/start`, `/backup/events/{job_id}`)
5. **Done**: Docker Compose (`docker-compose.yml`) — portal + netdriver-agent; see root `README.md`