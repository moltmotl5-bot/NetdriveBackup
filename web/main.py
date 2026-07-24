from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from nccm.backup.job_manager import get_job, start_backup_job_async
from nccm.config import netdriver_url, store_dir
from nccm.netdriver.client import NetDriverClient
from nccm.registry.csv import load_devices_csv
from web.auth import authenticate, ensure_portal_can_start
from web.api import router as api_router
from web.admin_users import build_admin_users_router
from web.admin_api_tokens import build_admin_api_tokens_router
from web.admin_audit import build_admin_audit_router
from web.account import build_account_router
from web.deps import (
    current_user,
    require_operator,
    require_user,
    role_can_operate,
    session_role,
    session_user_id,
    session_username,
    set_session_user,
)
from nccm.auth.audit import audit_portal_login, write_audit

load_dotenv()

_WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="NetdriverBackup NCCM v3")
_secret = os.environ.get("NCCM_SESSION_SECRET") or secrets.token_hex(32)
app.include_router(api_router, prefix="/api/v1")

templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
static_path = _WEB_DIR / "static"
if static_path.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

NAV = [
    ("backup", "批次備份", "/backup"),
    ("inventory", "設備總表與版控", "/inventory"),
    ("neighbors", "CDP/LLDP 鄰居", "/neighbors"),
    ("interfaces", "Interface Map", "/interfaces"),
    ("schedules", "排程備份", "/schedules"),
]
ADMIN_NAV = [
    ("admin_users", "使用者管理", "/admin/users"),
    ("admin_api_tokens", "API Token", "/admin/api-tokens"),
    ("admin_audit", "審計日誌", "/admin/audit"),
]


def _nav_for_role(role: str) -> list[tuple[str, str, str]]:
    items = list(NAV)
    if role == "viewer":
        items = [x for x in items if x[0] != "backup"]
    if role == "admin":
        items = [*items, *ADMIN_NAV]
    return items


_PUBLIC_PATHS = {"/login", "/health", "/openapi.json", "/docs", "/redoc"}
_MUST_CHANGE_PASSWORD_ALLOW = {"/account/change-password", "/logout"}


class SessionGateMiddleware:
    """Pure ASGI gate — avoids BaseHTTPMiddleware breaking request.session in TestClient."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if (
            path.startswith("/static")
            or path in _PUBLIC_PATHS
            or path.startswith("/api/v1")
        ):
            await self.app(scope, receive, send)
            return
        session = scope.get("session") or {}
        if not session.get("user"):
            response = RedirectResponse(url="/login", status_code=303)
            await response(scope, receive, send)
            return
        if session.get("must_change_password"):
            if path not in _MUST_CHANGE_PASSWORD_ALLOW:
                response = RedirectResponse(url="/account/change-password", status_code=303)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(SessionGateMiddleware)
app.add_middleware(SessionMiddleware, secret_key=_secret)


@app.on_event("startup")
async def _check_portal_env() -> None:
    ensure_portal_can_start()
    try:
        from nccm.backup.schedule import start_schedule_watcher

        start_schedule_watcher()
    except Exception:
        pass


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": "登入", "error": None},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    portal_user = authenticate(username, password)
    if portal_user:
        set_session_user(
            request,
            username=portal_user.username,
            role=portal_user.role,
            user_id=portal_user.id,
            must_change_password=portal_user.must_change_password,
        )
        audit_portal_login(request, portal_user.username, True)
        if portal_user.must_change_password:
            return RedirectResponse(url="/account/change-password", status_code=303)
        dest = "/inventory" if portal_user.role == "viewer" else "/backup"
        return RedirectResponse(url=dest, status_code=303)
    audit_portal_login(request, username, False)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": "登入", "error": "帳號或密碼錯誤"},
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/backup", status_code=302)


@app.get("/health")
async def health():
    agent_ok = NetDriverClient().health()
    return {
        "status": "ok" if agent_ok else "degraded",
        "portal": "nccm-v3",
        "netdriver_agent": agent_ok,
        "store_dir": str(store_dir()),
    }


def _ctx(request: Request, page: str, **extra):
    agent_ok = NetDriverClient().health()
    role = session_role(request)
    minimal = bool(extra.get("force_minimal_nav"))
    base = {
        "request": request,
        "nav": [] if minimal else _nav_for_role(role),
        "active": page,
        "store": str(store_dir()),
        "agent_url": netdriver_url(),
        "agent_ok": agent_ok,
        "agent_status": "Online" if agent_ok else "Offline",
        "portal_user": session_username(request),
        "portal_role": role,
        "current_uid": session_user_id(request),
    }
    base.update(extra)
    return base


app.include_router(build_account_router(templates, _ctx))
app.include_router(build_admin_users_router(templates, _ctx))
app.include_router(build_admin_api_tokens_router(templates, _ctx))
app.include_router(build_admin_audit_router(templates, _ctx))


@app.get("/backup", response_class=HTMLResponse)
async def backup_page(
    request: Request,
    user: str = Depends(require_operator),
    run_id: str = "",
):
    return templates.TemplateResponse(
        request,
        "backup.html",
        _ctx(
            request,
            "backup",
            job_id=run_id,
            results=None,
            result_run_id=None,
            log_lines=[],
            error=None,
            job_status=None,
        ),
    )


def _devices_from_csv_text(csv_text: str) -> list:
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(csv_text)
        tmp_path = Path(tmp.name)
    try:
        return load_devices_csv(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/backup/start")
async def backup_start(
    request: Request,
    user: str = Depends(require_operator),
    csv_text: Annotated[str, Form()] = "",
    csv_file: UploadFile | None = File(None),
    ssh_user: Annotated[str, Form()] = "",
    ssh_password: Annotated[str, Form()] = "",
):
    try:
        body = (csv_text or "").strip()
        if csv_file and csv_file.filename:
            raw = await csv_file.read()
            body = raw.decode("utf-8-sig", errors="replace").strip()
        if not body:
            raise ValueError("請上傳 CSV 檔案，或在文字框貼上設備清單")
        devices = _devices_from_csv_text(body)
        job_id = start_backup_job_async(
            devices,
            username=ssh_user,
            password=ssh_password,
            agent_url=netdriver_url(),
        )
        write_audit(
            request=request,
            event="backup_start",
            success=True,
            actor=user,
            detail=f"job_id={job_id};devices={len(devices)}",
        )
        return RedirectResponse(url=f"/backup?run_id={job_id}", status_code=303)
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "backup.html",
            _ctx(request, "backup", job_id="", error=str(exc), log_lines=[]),
            status_code=400,
        )


@app.get("/backup/events/{job_id}")
async def backup_events(
    job_id: str,
    request: Request,
    user: str = Depends(require_operator),
):
    job = get_job(job_id)
    if not job:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'message': 'unknown job'})}\n\n"

        return StreamingResponse(_err(), media_type="text/event-stream")

    async def _stream():
        idx = 0
        while True:
            if await request.is_disconnected():
                break
            lines, _status, payload = job.snapshot(log_from=idx)
            idx += len(lines)
            for line in lines:
                chunk = json.dumps({"type": "log", "line": line}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
            if payload is not None:
                chunk = json.dumps({"type": "complete", **payload}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/backup", response_class=HTMLResponse)
async def backup_run_legacy(
    request: Request,
    user: str = Depends(require_operator),
    csv_text: Annotated[str, Form()] = "",
    ssh_user: Annotated[str, Form()] = "",
    ssh_password: Annotated[str, Form()] = "",
):
    """Legacy form action — enqueues background job (same as /backup/start)."""
    return await backup_start(
        request,
        user=user,
        csv_text=csv_text,
        ssh_user=ssh_user,
        ssh_password=ssh_password,
    )


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    user: str = Depends(current_user),
    q: str = "",
    site: str = "",
    vendor: str = "",
    device_id: str = "",
    snapshot_id: int = 0,
    compare_id: int = 0,
):
    from nccm.storage.config_diff import diff_snapshots
    from nccm.storage.index_db import (
        get_snapshot,
        list_inventory_display,
        list_sites,
        list_snapshots_for_device,
        list_vendors,
        read_config_text,
    )

    rows = list_inventory_display(query=q, site=site, vendor=vendor)
    sites = list_sites()
    vendors = list_vendors()
    snapshots = []
    config_preview = ""
    selected_snap = None
    sid = 0
    diff_text = ""
    diff_meta = ""
    if device_id:
        snapshots = list_snapshots_for_device(device_id)
        sid = snapshot_id or (snapshots[0].id if snapshots else 0)
        if sid:
            selected_snap = get_snapshot(sid)
            if selected_snap:
                config_preview = read_config_text(sid)
        if sid and compare_id and compare_id != sid:
            try:
                dr = diff_snapshots(device_id, compare_id, sid)
                diff_text = dr.unified
                diff_meta = f"{dr.a_label} → {dr.b_label}" + (
                    "（相同）" if dr.identical else "（有差異）"
                )
            except ValueError as e:
                diff_text = str(e)
                diff_meta = "diff error"

    return templates.TemplateResponse(
        request,
        "inventory.html",
        _ctx(
            request,
            "inventory",
            rows=rows,
            sites=sites,
            vendors=vendors,
            q=q,
            site_filter=site,
            vendor_filter=vendor,
            device_id=device_id,
            snapshots=snapshots,
            snapshot_id=selected_snap.id if selected_snap else 0,
            compare_id=compare_id,
            config_preview=config_preview,
            diff_text=diff_text,
            diff_meta=diff_meta,
            rebuild_msg=None,
        ),
    )


@app.post("/inventory/rebuild", response_class=HTMLResponse)
async def inventory_rebuild(request: Request, user: str = Depends(require_operator)):
    from nccm.storage.index_db import rebuild_index

    d, s = rebuild_index()
    write_audit(
        request=request,
        event="inventory_rebuild",
        success=True,
        actor=user,
        detail=f"devices={d};snapshots={s}",
    )
    return RedirectResponse(
        url=f"/inventory?rebuild_ok={d}d{s}s",
        status_code=303,
    )


@app.get("/inventory/partial/table", response_class=HTMLResponse)
async def inventory_table_partial(
    request: Request,
    user: str = Depends(current_user),
    q: str = "",
    site: str = "",
    vendor: str = "",
    device_id: str = "",
):
    from nccm.storage.index_db import list_inventory_display

    rows = list_inventory_display(query=q, site=site, vendor=vendor)
    return templates.TemplateResponse(
        request,
        "partials/inventory_table.html",
        _ctx(request, "inventory", rows=rows, device_id=device_id),
    )


@app.get("/inventory/partial/detail", response_class=HTMLResponse)
async def inventory_detail_partial(
    request: Request,
    user: str = Depends(current_user),
    device_id: str = "",
    snapshot_id: int = 0,
    compare_id: int = 0,
):
    from nccm.storage.config_diff import diff_snapshots
    from nccm.storage.index_db import (
        get_snapshot,
        list_snapshots_for_device,
        read_config_text,
    )

    snapshots = list_snapshots_for_device(device_id) if device_id else []
    sid = snapshot_id or (snapshots[0].id if snapshots else 0)
    config_preview = ""
    selected_snap = None
    if sid:
        selected_snap = get_snapshot(sid)
        if selected_snap:
            config_preview = read_config_text(sid)

    diff_text = ""
    diff_meta = ""
    cid = compare_id
    if device_id and sid and cid and cid != sid:
        try:
            dr = diff_snapshots(device_id, cid, sid)
            diff_text = dr.unified
            diff_meta = f"{dr.a_label} → {dr.b_label}" + (
                "（相同）" if dr.identical else "（有差異）"
            )
        except ValueError as e:
            diff_text = str(e)
            diff_meta = "diff error"

    return templates.TemplateResponse(
        request,
        "partials/inventory_detail.html",
        _ctx(
            request,
            "inventory",
            device_id=device_id,
            snapshots=snapshots,
            snapshot_id=sid,
            compare_id=cid,
            config_preview=config_preview,
            diff_text=diff_text,
            diff_meta=diff_meta,
        ),
    )


@app.get("/inventory/download/config")
async def inventory_download_config(
    request: Request,
    snapshot_id: int,
    device_id: str = "",
    user: str = Depends(require_operator),
):
    """Download full config.txt for the selected snapshot (Running-Configuration)."""
    from nccm.storage.index_db import get_snapshot, parse_device_id

    if snapshot_id <= 0:
        raise HTTPException(status_code=400, detail="snapshot_id required")
    snap = get_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="snapshot not found")
    if device_id and snap.device_id != device_id:
        raise HTTPException(status_code=403, detail="snapshot does not belong to device")
    path = Path(snap.snapshot_path) / "config.txt"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="config.txt not found")
    _site, ip, _port, host = parse_device_id(snap.device_id)
    ts = path.parent.name or (snap.created_at or "snapshot")
    safe_host = re.sub(r"[^\w.\-]+", "_", (snap.hostname or host or "unknown"))[:64]
    filename = f"{ip}_{safe_host}_{ts}_config.txt"
    write_audit(
        request=request,
        event="config_download",
        success=True,
        actor=user,
        detail=f"snapshot_id={snapshot_id};device_id={snap.device_id}",
    )
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=filename,
    )


@app.post("/inventory/retention", response_class=HTMLResponse)
async def inventory_retention(
    request: Request,
    user: str = Depends(require_operator),
    keep_last: Annotated[int, Form()] = 10,
    dry_run: Annotated[str, Form()] = "1",
    device_id: Annotated[str, Form()] = "",
):
    from nccm.storage.retention import apply_retention, plan_retention

    plan = plan_retention(keep_last=keep_last, device_id=device_id or None)
    is_dry = dry_run != "0"
    result = apply_retention(plan, dry_run=is_dry)
    q = "dry" if is_dry else "done"
    n = result.get("would_delete") if is_dry else result.get("deleted")
    write_audit(
        request=request,
        event="snapshot_retention",
        success=True,
        actor=user,
        detail=f"dry_run={is_dry};keep_last={plan.keep_last};n={n};device_id={device_id or '*'}",
    )
    return RedirectResponse(
        url=f"/inventory?retention={q}&n={n}&keep={plan.keep_last}",
        status_code=303,
    )


def _schedules_ctx(request: Request, **extra):
    from nccm.backup.schedule import list_schedule_runs, list_schedules
    from nccm.backup.secrets import secrets_configured, secrets_key_source

    role = session_role(request)
    base = _ctx(
        request,
        "schedules",
        schedules=list_schedules(),
        schedule_runs=list_schedule_runs(limit=30),
        can_operate=role_can_operate(role),
        secrets_configured=secrets_configured(),
        secrets_key_source=secrets_key_source(),
    )
    base.update(extra)
    return base


@app.get("/schedules", response_class=HTMLResponse)
async def schedules_page(
    request: Request,
    user: str = Depends(require_user),
    message: str = "",
    error: str = "",
):
    return templates.TemplateResponse(
        request,
        "schedules.html",
        _schedules_ctx(request, message=message or None, error=error or None),
    )


@app.post("/schedules/upload", response_class=HTMLResponse)
async def schedules_upload(
    request: Request,
    user: str = Depends(require_operator),
    name: Annotated[str, Form()] = "",
    interval_days: Annotated[int, Form()] = 1,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    enable_password: Annotated[str, Form()] = "",
    csv_file: UploadFile = File(...),
    edit_schedule_id: Annotated[int, Form()] = 0,
):
    from nccm.backup.schedule_draft import create_draft_from_upload

    if not csv_file.filename:
        return templates.TemplateResponse(
            request,
            "schedules.html",
            _schedules_ctx(request, error="請選擇 CSV 檔案"),
            status_code=400,
        )
    raw = await csv_file.read()
    try:
        draft = create_draft_from_upload(
            name=name,
            csv_bytes=raw,
            csv_filename=csv_file.filename or "upload.csv",
            interval_days=interval_days,
            username=username,
            password=password,
            enable_password=enable_password,
            created_by=user,
            edit_schedule_id=edit_schedule_id or None,
        )
        write_audit(
            request=request,
            event="schedule_csv_probe",
            success=True,
            actor=user,
            detail=f"draft={draft.id};ok={draft.ok_count};fail={draft.fail_count}",
        )
    except ValueError as exc:
        write_audit(
            request=request,
            event="schedule_csv_probe",
            success=False,
            actor=user,
            detail=str(exc)[:200],
        )
        return templates.TemplateResponse(
            request,
            "schedules.html",
            _schedules_ctx(request, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse(url=f"/schedules/preview/{draft.id}", status_code=303)


@app.get("/schedules/preview/{draft_id}", response_class=HTMLResponse)
async def schedules_preview(
    request: Request,
    draft_id: str,
    user: str = Depends(require_operator),
):
    from nccm.backup.schedule_draft import get_draft

    try:
        draft = get_draft(draft_id)
    except ValueError:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "schedule_preview.html",
        _schedules_ctx(request, draft=draft),
    )


@app.post("/schedules/preview/{draft_id}/confirm", response_class=HTMLResponse)
async def schedules_confirm(
    request: Request,
    draft_id: str,
    user: str = Depends(require_operator),
):
    from nccm.backup.schedule_draft import confirm_draft

    try:
        result = confirm_draft(draft_id)
        sch = result.schedule
        if result.key_created:
            write_audit(
                request=request,
                event="secrets_key_init",
                success=True,
                actor=user,
                detail=f"source={result.key_source or 'store'}",
            )
        write_audit(
            request=request,
            event="schedule_csv_confirm",
            success=True,
            actor=user,
            detail=f"id={sch.id};devices={sch.device_count}",
        )
        msg = f"排程「{sch.name}」已建立（{sch.device_count} 台設備）"
        if result.key_created:
            msg += "；加密主金鑰已初始化，請備份 store 目錄"
        return templates.TemplateResponse(
            request,
            "schedules.html",
            _schedules_ctx(request, message=msg),
        )
    except ValueError as exc:
        from nccm.backup.schedule_draft import get_draft

        write_audit(
            request=request,
            event="schedule_csv_confirm",
            success=False,
            actor=user,
            detail=str(exc)[:200],
        )
        try:
            draft = get_draft(draft_id)
        except ValueError:
            raise HTTPException(404) from exc
        return templates.TemplateResponse(
            request,
            "schedule_preview.html",
            _schedules_ctx(request, error=str(exc), draft=draft),
            status_code=400,
        )


@app.get("/schedules/{schedule_id}/devices", response_class=HTMLResponse)
async def schedules_devices_partial(
    request: Request,
    schedule_id: int,
    user: str = Depends(require_user),
):
    from nccm.backup.schedule import get_schedule, load_schedule_devices

    sch = get_schedule(schedule_id)
    if not sch:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "partials/schedule_devices.html",
        {"request": request, "schedule": sch, "devices": load_schedule_devices(sch)},
    )


@app.post("/schedules/{schedule_id}/update", response_class=HTMLResponse)
async def schedules_update_meta(
    request: Request,
    schedule_id: int,
    user: str = Depends(require_operator),
    name: Annotated[str, Form()] = "",
    interval_days: Annotated[int, Form()] = 1,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    enable_password: Annotated[str, Form()] = "",
):
    from nccm.backup.schedule import update_schedule

    try:
        result = update_schedule(
            schedule_id,
            name=name,
            interval_days=interval_days,
            username=username,
            password=password if password else None,
            enable_password=enable_password if enable_password else None,
        )
        sch = result.schedule
        write_audit(
            request=request,
            event="schedule_update",
            success=True,
            actor=user,
            detail=f"id={sch.id};name={sch.name}",
        )
        msg = "已更新排程"
    except ValueError as exc:
        msg = None
        write_audit(
            request=request,
            event="schedule_update",
            success=False,
            actor=user,
            detail=f"id={schedule_id};{str(exc)[:180]}",
        )
        return templates.TemplateResponse(
            request,
            "schedules.html",
            _schedules_ctx(request, error=str(exc)),
        )
    return templates.TemplateResponse(
        request,
        "schedules.html",
        _schedules_ctx(request, message=msg),
    )


@app.post("/schedules/{schedule_id}/run", response_class=HTMLResponse)
async def schedules_run_now(
    request: Request,
    schedule_id: int,
    user: str = Depends(require_operator),
):
    from nccm.backup.schedule import get_schedule, run_schedule

    sch = get_schedule(schedule_id)
    if not sch:
        raise HTTPException(404)
    try:
        r = run_schedule(schedule_id, triggered_by=f"manual:{user}")
        ok = bool(r.get("ok"))
        write_audit(
            request=request,
            event="schedule_run_start" if ok else "schedule_run_skipped",
            success=ok,
            actor=user,
            detail=f"id={schedule_id};job={r.get('job_id', '')};skipped={r.get('skipped', False)}",
        )
        if r.get("skipped"):
            err = r.get("error") or "已跳過"
            msg = None
        elif ok:
            msg = r.get("message") or f"備份已啟動（{r.get('device_count', 0)} 台）"
            err = None
        else:
            err = r.get("error") or "執行失敗"
            msg = None
    except ValueError as exc:
        msg, err = None, str(exc)
        write_audit(
            request=request,
            event="schedule_run_start",
            success=False,
            actor=user,
            detail=f"id={schedule_id};{str(exc)[:180]}",
        )
    return templates.TemplateResponse(
        request,
        "schedules.html",
        _schedules_ctx(request, message=msg, error=err),
    )


@app.post("/schedules/{schedule_id}/toggle", response_class=HTMLResponse)
async def schedules_toggle(
    request: Request,
    schedule_id: int,
    user: str = Depends(require_operator),
):
    from nccm.backup.schedule import get_schedule, set_enabled

    sch = get_schedule(schedule_id)
    if not sch:
        raise HTTPException(404)
    new_enabled = not sch.enabled
    try:
        set_enabled(schedule_id, new_enabled)
        write_audit(
            request=request,
            event="schedule_toggle",
            success=True,
            actor=user,
            detail=f"id={schedule_id};enabled={1 if new_enabled else 0}",
        )
        msg, err = "已更新啟用狀態", None
    except ValueError as exc:
        msg, err = None, str(exc)
        write_audit(
            request=request,
            event="schedule_toggle",
            success=False,
            actor=user,
            detail=f"id={schedule_id};{str(exc)[:180]}",
        )
    return templates.TemplateResponse(
        request,
        "schedules.html",
        _schedules_ctx(request, message=msg, error=err),
    )


@app.post("/schedules/{schedule_id}/delete", response_class=HTMLResponse)
async def schedules_delete(
    request: Request,
    schedule_id: int,
    user: str = Depends(require_operator),
):
    from nccm.backup.schedule import delete_schedule, get_schedule

    sch = get_schedule(schedule_id)
    if not sch:
        raise HTTPException(404)
    delete_schedule(schedule_id)
    write_audit(
        request=request,
        event="schedule_delete",
        success=True,
        actor=user,
        detail=f"id={schedule_id};name={sch.name}",
    )
    return templates.TemplateResponse(
        request,
        "schedules.html",
        _schedules_ctx(request, message="已刪除排程", error=None),
    )


@app.get("/neighbors", response_class=HTMLResponse)
async def neighbors_page(
    request: Request,
    user: str = Depends(current_user),
    q: str = "",
    site: str = "",
    vendor: str = "",
    device_key: str = "",
    snapshot_ts: str = "",
):
    from nccm.inventory.neighbors import (
        neighbor_device_rows,
        neighbor_display_rows,
        neighbors_for_device,
        resolve_neighbor_context,
    )
    from nccm.storage.index_db import list_sites, list_vendors

    rows, lookup = neighbor_device_rows(query=q, site=site, vendor=vendor)
    sites = list_sites()
    vendors = list_vendors()
    neighbor_rows: list = []
    display_neighbors: list = []
    cdp_status = lldp_status = ""
    version_label = ""
    if device_key:
        neighbor_rows, cdp_status, lldp_status, version_label = neighbors_for_device(
            device_key, snapshot_ts=snapshot_ts, lookup=lookup
        )
        display_neighbors = neighbor_display_rows(neighbor_rows, lookup)

    device_vendor = ""
    if device_key:
        _dr, _log, *_rest = resolve_neighbor_context(device_key)
        device_vendor = (_log.vendor if _log else (_dr.vendor if _dr else "")) or ""

    return templates.TemplateResponse(
        request,
        "neighbors.html",
        _ctx(
            request,
            "neighbors",
            rows=rows,
            sites=sites,
            vendors=vendors,
            q=q,
            site_filter=site,
            vendor_filter=vendor,
            device_key=device_key,
            snapshot_ts=version_label or snapshot_ts,
            neighbor_rows=display_neighbors,
            cdp_status=cdp_status,
            lldp_status=lldp_status,
            version_label=version_label,
            device_vendor=device_vendor,
        ),
    )


@app.get("/neighbors/partial/table", response_class=HTMLResponse)
async def neighbors_table_partial(
    request: Request,
    user: str = Depends(current_user),
    q: str = "",
    site: str = "",
    vendor: str = "",
    device_key: str = "",
):
    from nccm.inventory.neighbors import neighbor_device_rows

    rows, _ = neighbor_device_rows(query=q, site=site, vendor=vendor)
    return templates.TemplateResponse(
        request,
        "partials/neighbors_table.html",
        _ctx(request, "neighbors", rows=rows, device_key=device_key),
    )


@app.get("/neighbors/partial/detail", response_class=HTMLResponse)
async def neighbors_detail_partial(
    request: Request,
    user: str = Depends(current_user),
    device_key: str = "",
    snapshot_ts: str = "",
):
    from nccm.inventory.neighbors import (
        neighbor_device_rows,
        neighbor_display_rows,
        neighbors_for_device,
        resolve_neighbor_context,
    )

    _, lookup = neighbor_device_rows()
    neighbor_rows, cdp, lldp, version_label = neighbors_for_device(
        device_key, snapshot_ts=snapshot_ts, lookup=lookup
    )
    display_neighbors = neighbor_display_rows(neighbor_rows, lookup)
    from nccm.parsers.cdp_lldp import list_device_backup_versions

    versions: list[str] = []
    device_vendor = ""
    if device_key:
        dr, log, store, _ph, _v, _did = resolve_neighbor_context(device_key)
        device_vendor = (log.vendor if log else (dr.vendor if dr else "")) or ""
        versions = list_device_backup_versions(str(store), 10)

    return templates.TemplateResponse(
        request,
        "partials/neighbors_detail.html",
        _ctx(
            request,
            "neighbors",
            device_key=device_key,
            versions=versions,
            snapshot_ts=version_label,
            neighbor_rows=display_neighbors,
            cdp_status=cdp,
            lldp_status=lldp,
            device_vendor=device_vendor,
        ),
    )


@app.get("/interfaces", response_class=HTMLResponse)
async def interfaces_page(
    request: Request,
    user: str = Depends(current_user),
    q: str = "",
    site: str = "",
    vendor: str = "",
    device_id: str = "",
    snapshot_ts: str = "",
):
    from nccm.inventory.interface_map import interface_map_for_device
    from nccm.inventory.neighbors import neighbor_device_rows
    from nccm.storage.index_db import list_sites, list_vendors

    rows, _ = neighbor_device_rows(query=q, site=site, vendor=vendor)
    sites = list_sites()
    vendors = list_vendors()
    iface_data: dict = {}
    if device_id:
        iface_data = interface_map_for_device(device_id, snapshot_ts=snapshot_ts)

    return templates.TemplateResponse(
        request,
        "interfaces.html",
        _ctx(
            request,
            "interfaces",
            rows=rows,
            sites=sites,
            vendors=vendors,
            q=q,
            site_filter=site,
            vendor_filter=vendor,
            device_id=device_id,
            iface=iface_data,
        ),
    )


@app.get("/interfaces/partial/detail", response_class=HTMLResponse)
async def interfaces_detail_partial(
    request: Request,
    user: str = Depends(current_user),
    device_id: str = "",
    snapshot_ts: str = "",
):
    from nccm.inventory.interface_map import interface_map_for_device

    iface = interface_map_for_device(device_id, snapshot_ts=snapshot_ts) if device_id else {}
    return templates.TemplateResponse(
        request,
        "partials/interfaces_detail.html",
        _ctx(request, "interfaces", device_id=device_id, iface=iface),
    )