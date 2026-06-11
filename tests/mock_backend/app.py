"""
Mock Declaw API backend for integration testing.

Implements the full REST API with in-memory state, real subprocess execution,
and real filesystem operations scoped to per-sandbox temp directories.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

app = FastAPI(title="Declaw Mock Backend")

# In-memory state
_sandboxes: Dict[str, Dict[str, Any]] = {}
_sandbox_dirs: Dict[str, str] = {}
_processes: Dict[str, Dict[int, Dict[str, Any]]] = {}
_pid_counter = 100


def _next_pid() -> int:
    global _pid_counter
    _pid_counter += 1
    return _pid_counter


def _get_sandbox(sandbox_id: str) -> Dict[str, Any]:
    if sandbox_id not in _sandboxes:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")
    return _sandboxes[sandbox_id]


def _get_sandbox_dir(sandbox_id: str) -> str:
    _get_sandbox(sandbox_id)
    if sandbox_id not in _sandbox_dirs:
        d = tempfile.mkdtemp(prefix=f"declaw-{sandbox_id}-")
        # Create per-sandbox /tmp, /home/user so commands behave like a real VM
        os.makedirs(os.path.join(d, "tmp"), exist_ok=True)
        os.makedirs(os.path.join(d, "home", "user"), exist_ok=True)
        _sandbox_dirs[sandbox_id] = d
    return _sandbox_dirs[sandbox_id]


# --- Sandbox CRUD ---


@app.post("/sandboxes", status_code=201)
async def create_sandbox(request: Request):
    body = await request.json()
    sandbox_id = f"sbx-{uuid.uuid4().hex[:8]}"
    now = datetime.datetime.utcnow().isoformat()
    sandbox = {
        "sandbox_id": sandbox_id,
        "template_id": f"tpl-{body.get('template', 'base')}",
        "name": body.get("template", "base"),
        "metadata": body.get("metadata", {}),
        "envs": body.get("envs", {}),
        "network": body.get("network"),
        "security": body.get("security"),
        "lifecycle": body.get("lifecycle"),
        "state": "running",
        "started_at": now,
        "end_at": None,
        "timeout": body.get("timeout", 300),
        "envd_access_token": f"envd-tok-{uuid.uuid4().hex[:8]}",
        "sandbox_domain": "mock.declaw.dev",
        "traffic_access_token": f"traffic-{uuid.uuid4().hex[:8]}",
    }
    _sandboxes[sandbox_id] = sandbox
    _processes[sandbox_id] = {}
    d = tempfile.mkdtemp(prefix=f"declaw-{sandbox_id}-")
    _sandbox_dirs[sandbox_id] = d
    return sandbox


@app.get("/sandboxes/{sandbox_id}")
async def get_sandbox(sandbox_id: str):
    return _get_sandbox(sandbox_id)


@app.get("/sandboxes")
async def list_sandboxes(limit: int = 50, next_token: Optional[str] = None):
    all_sbx = list(_sandboxes.values())
    return {"sandboxes": all_sbx[:limit], "next_token": None}


@app.delete("/sandboxes/{sandbox_id}")
async def kill_sandbox(sandbox_id: str):
    sbx = _get_sandbox(sandbox_id)
    sbx["state"] = "killed"
    if sandbox_id in _sandbox_dirs:
        shutil.rmtree(_sandbox_dirs[sandbox_id], ignore_errors=True)
        del _sandbox_dirs[sandbox_id]
    return {"killed": True}


@app.get("/sandboxes/{sandbox_id}/status")
async def sandbox_status(sandbox_id: str):
    sbx = _get_sandbox(sandbox_id)
    return {"is_running": sbx["state"] == "running"}


@app.patch("/sandboxes/{sandbox_id}/timeout")
async def set_timeout(sandbox_id: str, request: Request):
    sbx = _get_sandbox(sandbox_id)
    body = await request.json()
    sbx["timeout"] = body["timeout"]
    return {"ok": True}


@app.get("/sandboxes/{sandbox_id}/metrics")
async def get_metrics(sandbox_id: str):
    _get_sandbox(sandbox_id)
    return [
        {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "cpu_usage_percent": 12.5,
            "memory_usage_mb": 128.0,
            "disk_usage_mb": 50.0,
        }
    ]


@app.post("/sandboxes/{sandbox_id}/pause")
async def pause_sandbox(sandbox_id: str):
    sbx = _get_sandbox(sandbox_id)
    sbx["state"] = "paused"
    return {}


@app.post("/sandboxes/{sandbox_id}/snapshots")
async def create_snapshot(sandbox_id: str):
    _get_sandbox(sandbox_id)
    snap_id = f"snap-{uuid.uuid4().hex[:8]}"
    return {
        "snapshot_id": snap_id,
        "sandbox_id": sandbox_id,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }


# --- Commands ---


def _sandbox_env(sandbox_id: str, sbx: dict, extra_envs: dict = None) -> dict:
    """Build environment for command execution scoped to the sandbox directory."""
    sandbox_dir = _get_sandbox_dir(sandbox_id)
    envs = {}
    # Only inherit minimal host env (PATH, LANG), not secrets
    for k in ("PATH", "LANG", "LC_ALL", "SHELL"):
        if k in os.environ:
            envs[k] = os.environ[k]
    envs.update(sbx.get("envs", {}))
    if extra_envs:
        envs.update(extra_envs)
    envs["DECLAW_SANDBOX_ID"] = sandbox_id
    envs["DECLAW_SANDBOX"] = "true"
    envs["HOME"] = os.path.join(sandbox_dir, "home", "user")
    envs["TMPDIR"] = os.path.join(sandbox_dir, "tmp")
    return envs


@app.post("/sandboxes/{sandbox_id}/commands")
async def run_command(sandbox_id: str, request: Request):
    sbx = _get_sandbox(sandbox_id)
    body = await request.json()
    cmd = body["cmd"]
    background = body.get("background", False)
    sandbox_dir = _get_sandbox_dir(sandbox_id)
    envs = _sandbox_env(sandbox_id, sbx, body.get("envs"))
    cwd = body.get("cwd") or sandbox_dir

    if background:
        pid = _next_pid()
        _processes[sandbox_id][pid] = {"cmd": cmd, "envs": envs, "cwd": cwd, "is_pty": False}
        return {"pid": pid}

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=body.get("timeout", 60),
            env=envs,
            cwd=cwd,
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "timeout", "exit_code": 124}


@app.get("/sandboxes/{sandbox_id}/commands")
async def list_commands(sandbox_id: str):
    _get_sandbox(sandbox_id)
    procs = _processes.get(sandbox_id, {})
    return [
        {"pid": pid, "cmd": p["cmd"], "is_pty": p.get("is_pty", False), "envs": {}}
        for pid, p in procs.items()
    ]


@app.delete("/sandboxes/{sandbox_id}/commands/{pid}")
async def kill_command(sandbox_id: str, pid: int):
    _get_sandbox(sandbox_id)
    procs = _processes.get(sandbox_id, {})
    killed = pid in procs
    procs.pop(pid, None)
    return {"killed": killed}


@app.post("/sandboxes/{sandbox_id}/commands/{pid}/stdin")
async def send_stdin(sandbox_id: str, pid: int, request: Request):
    _get_sandbox(sandbox_id)
    return {}


@app.get("/sandboxes/{sandbox_id}/commands/{pid}/wait")
async def wait_command(sandbox_id: str, pid: int):
    sbx = _get_sandbox(sandbox_id)
    proc_info = _processes.get(sandbox_id, {}).get(pid)
    if not proc_info:
        return {"stdout": "", "stderr": "process not found", "exit_code": 1}
    envs = _sandbox_env(sandbox_id, sbx, proc_info.get("envs"))
    cwd = proc_info.get("cwd") or _get_sandbox_dir(sandbox_id)
    try:
        result = subprocess.run(
            proc_info["cmd"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            env=envs,
            cwd=cwd,
        )
        _processes[sandbox_id].pop(pid, None)
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "timeout", "exit_code": 124}


# --- Filesystem ---


@app.get("/sandboxes/{sandbox_id}/files")
async def read_file(sandbox_id: str, path: str, username: str = "user"):
    base = _get_sandbox_dir(sandbox_id)
    full = os.path.join(base, path.lstrip("/"))
    if not os.path.exists(full):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    with open(full, "r") as f:
        return PlainTextResponse(f.read())


@app.post("/sandboxes/{sandbox_id}/files")
async def write_file(sandbox_id: str, request: Request):
    body = await request.json()
    base = _get_sandbox_dir(sandbox_id)
    fpath = body["path"]
    full = os.path.join(base, fpath.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    data = body["data"]
    with open(full, "w") as f:
        f.write(data)
    return {"path": fpath, "size": len(data)}


@app.post("/sandboxes/{sandbox_id}/files/batch")
async def write_files_batch(sandbox_id: str, request: Request):
    body = await request.json()
    base = _get_sandbox_dir(sandbox_id)
    results = []
    for entry in body["files"]:
        full = os.path.join(base, entry["path"].lstrip("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        data = entry["data"]
        with open(full, "w") as f:
            f.write(data)
        results.append({"path": entry["path"], "size": len(data)})
    return results


@app.get("/sandboxes/{sandbox_id}/files/list")
async def list_files(sandbox_id: str, path: str, depth: int = 1, username: str = "user"):
    base = _get_sandbox_dir(sandbox_id)
    full = os.path.join(base, path.lstrip("/"))
    if not os.path.isdir(full):
        return []
    entries = []
    for name in os.listdir(full):
        fp = os.path.join(full, name)
        rel = os.path.join(path, name)
        ftype = "dir" if os.path.isdir(fp) else "file"
        size = os.path.getsize(fp) if os.path.isfile(fp) else 0
        entries.append({"name": name, "path": rel, "type": ftype, "size": size})
    return entries


@app.get("/sandboxes/{sandbox_id}/files/exists")
async def file_exists(sandbox_id: str, path: str, username: str = "user"):
    base = _get_sandbox_dir(sandbox_id)
    full = os.path.join(base, path.lstrip("/"))
    return {"exists": os.path.exists(full)}


@app.get("/sandboxes/{sandbox_id}/files/info")
async def file_info(sandbox_id: str, path: str, username: str = "user"):
    base = _get_sandbox_dir(sandbox_id)
    full = os.path.join(base, path.lstrip("/"))
    if not os.path.exists(full):
        raise HTTPException(status_code=404, detail="Not found")
    name = os.path.basename(full)
    ftype = "dir" if os.path.isdir(full) else "file"
    size = os.path.getsize(full) if os.path.isfile(full) else 0
    return {"name": name, "path": path, "type": ftype, "size": size}


@app.delete("/sandboxes/{sandbox_id}/files")
async def remove_file(sandbox_id: str, path: str, username: str = "user"):
    base = _get_sandbox_dir(sandbox_id)
    full = os.path.join(base, path.lstrip("/"))
    if os.path.isdir(full):
        shutil.rmtree(full)
    elif os.path.exists(full):
        os.remove(full)
    return {}


@app.patch("/sandboxes/{sandbox_id}/files")
async def rename_file(sandbox_id: str, request: Request):
    body = await request.json()
    base = _get_sandbox_dir(sandbox_id)
    old = os.path.join(base, body["old_path"].lstrip("/"))
    new = os.path.join(base, body["new_path"].lstrip("/"))
    os.makedirs(os.path.dirname(new), exist_ok=True)
    os.rename(old, new)
    name = os.path.basename(new)
    ftype = "dir" if os.path.isdir(new) else "file"
    size = os.path.getsize(new) if os.path.isfile(new) else 0
    return {"name": name, "path": body["new_path"], "type": ftype, "size": size}


@app.post("/sandboxes/{sandbox_id}/files/mkdir")
async def make_dir(sandbox_id: str, request: Request):
    body = await request.json()
    base = _get_sandbox_dir(sandbox_id)
    full = os.path.join(base, body["path"].lstrip("/"))
    created = not os.path.exists(full)
    os.makedirs(full, exist_ok=True)
    return {"created": created}


@app.post("/sandboxes/{sandbox_id}/files/watch")
async def watch_dir(sandbox_id: str, request: Request):
    _get_sandbox(sandbox_id)
    return {}


# --- PTY ---


@app.post("/sandboxes/{sandbox_id}/pty")
async def create_pty(sandbox_id: str, request: Request):
    _get_sandbox(sandbox_id)
    body = await request.json()
    pid = _next_pid()
    procs = _processes.setdefault(sandbox_id, {})
    procs[pid] = {"cmd": "bash", "is_pty": True, "envs": body.get("envs", {})}
    return {"pid": pid}


@app.delete("/sandboxes/{sandbox_id}/pty/{pid}")
async def kill_pty(sandbox_id: str, pid: int):
    _get_sandbox(sandbox_id)
    procs = _processes.get(sandbox_id, {})
    killed = pid in procs
    procs.pop(pid, None)
    return {"killed": killed}


@app.post("/sandboxes/{sandbox_id}/pty/{pid}/stdin")
async def send_pty_input(sandbox_id: str, pid: int, request: Request):
    _get_sandbox(sandbox_id)
    return {}


@app.patch("/sandboxes/{sandbox_id}/pty/{pid}")
async def resize_pty(sandbox_id: str, pid: int, request: Request):
    _get_sandbox(sandbox_id)
    return {}


# --- Templates ---


@app.post("/templates/build")
async def build_template(request: Request):
    body = await request.json()
    build_id = f"build-{uuid.uuid4().hex[:8]}"
    status = "completed" if not body.get("background") else "building"
    return {
        "build_id": build_id,
        "status": status,
        "template_id": f"tpl-{body.get('alias', 'custom')}",
        "logs": ["Step 1: Building...", "Step 2: Done."],
    }


@app.get("/templates/builds/{build_id}")
async def get_build_status(build_id: str):
    return {"build_id": build_id, "status": "completed", "logs": ["Done."]}
