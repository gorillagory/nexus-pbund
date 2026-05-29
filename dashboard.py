import json
import os
import platform
import re
import shlex
import signal
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock, Thread

import psutil
import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from watchdog.observers import Observer

import prompts
from database import get_db
from engine import NexusWatcher, calculate_prompt_timeout
from models import (
    ChatSession,
    ExecutionChangedFile,
    ExecutionRun,
    FactoryEvent,
    Footprint,
    Message,
    Task,
    UserProfile,
    WorkPacket,
    WorkPacketTask,
    Workspace,
)
from src.api.project_routes import projects_blueprint
from src.services.codex_runner import CodexRunner
from src.services.ci_status import summarize_ci_status
from src.services.cost_ledger import append_cost_event, read_cost_events, summarize_cost_events
from src.services.factory_events import (
    create_factory_event,
    get_recent_execution_runs,
    get_recent_factory_events,
    serialize_changed_file,
    serialize_execution_run,
    serialize_factory_event,
    summarize_factory_state,
)
from src.services.git_changes import summarize_git_changes
from src.services.work_packet_parser import extract_codex_commands, parse_work_packet


active_watcher = None
active_watcher_lock = Lock()
telemetry_lock = Lock()
SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|authorization|bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"secret|token|sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})"
)
MANUAL_COST_TEXT_FIELDS = ("provider", "model", "source", "task_id", "notes")
PREFLIGHT_WORKFLOW_PATH = ".github/workflows/nexus-preflight.yml"
PREFLIGHT_STATUS_PATH = ".nexus/preflight_status.json"
PREFLIGHT_QUICK_COMMAND = ["python3", "scripts/nexus_preflight.py", "--quick"]
PREFLIGHT_STRICT_CI_COMMAND = ["python3", "scripts/nexus_preflight.py", "--quick", "--strict-clean"]
PREFLIGHT_TIMEOUT_SECONDS = 300
PREFLIGHT_OUTPUT_EXCERPT_CHARS = 6000


def _safe_manual_cost_text(payload, field, max_length, required=False):
    value = payload.get(field)
    if value is None:
        if required:
            return None, "{} is required.".format(field)
        return None, None

    if not isinstance(value, str):
        return None, "{} must be a string.".format(field)

    value = value.strip()
    if required and not value:
        return None, "{} is required.".format(field)
    if not value:
        return None, None
    if len(value) > max_length:
        return None, "{} is too long.".format(field)
    if SECRET_TEXT_PATTERN.search(value):
        return None, "{} must not contain secrets.".format(field)

    return value, None


def _safe_manual_cost_int(payload, field):
    value = payload.get(field)
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "{} must be a non-negative integer.".format(field)
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None, "{} must be a non-negative integer.".format(field)
    if coerced < 0:
        return None, "{} must be a non-negative integer.".format(field)
    return coerced, None


def _safe_manual_cost_float(payload, field):
    value = payload.get(field)
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "{} must be a non-negative number.".format(field)
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return None, "{} must be a non-negative number.".format(field)
    if coerced < 0:
        return None, "{} must be a non-negative number.".format(field)
    return round(coerced, 6), None


def _extract_cli_token_usage(output):
    if not output:
        return None

    usage = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            candidate = payload.get("token_usage") or payload.get("usage")
            if isinstance(candidate, dict):
                usage.update(candidate)

    patterns = {
        "input_tokens": r"(?i)(?:input|prompt)[_\s-]*tokens[\"']?\s*[:=]\s*(\d+)",
        "output_tokens": r"(?i)(?:output|completion)[_\s-]*tokens[\"']?\s*[:=]\s*(\d+)",
        "total_tokens": r"(?i)total[_\s-]*tokens[\"']?\s*[:=]\s*(\d+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            usage[key] = int(match.group(1))

    return usage or None


def append_codex_telemetry(event, base_dir=None):
    telemetry_root = os.path.abspath(base_dir or os.getcwd())
    telemetry_dir = os.path.join(telemetry_root, ".nexus")
    telemetry_path = os.path.join(telemetry_dir, "codex_telemetry.jsonl")
    os.makedirs(telemetry_dir, exist_ok=True)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with telemetry_lock:
        with open(telemetry_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=True) + "\n")


def get_project_metadata(path):
    project_path = os.path.abspath(os.path.expanduser(path))
    branch = None
    git_dir = os.path.join(project_path, ".git")

    if os.path.exists(git_dir):
        try:
            branch_result = subprocess.run(
                ["git", "-C", project_path, "branch", "--show-current"],
                capture_output=True,
                check=False,
                text=True,
                timeout=0.5,
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            branch = None

    stack = []
    for marker, label, icons in (
        ("artisan", "Laravel", ["laravel"]),
        ("package.json", "Node / Vue", ["nodejs", "vuejs"]),
        ("requirements.txt", "Python", ["python"]),
    ):
        if os.path.exists(os.path.join(project_path, marker)):
            stack.append({"name": label, "icons": icons})

    ports = []
    seen_ports = set()
    port_variable_pattern = re.compile(
        r"(?im)^\s*(?P<label>[A-Z][A-Z0-9_]*PORT)\s*[:=]\s*[\"']?(?P<port>\d{2,5})"
    )
    port_default_pattern = re.compile(
        r"\$\{(?P<label>[A-Z][A-Z0-9_]*PORT):-?(?P<port>\d{2,5})\}"
    )
    compose_port_pattern = re.compile(
        r"""(?m)^\s*-\s*["']?(?:\d{1,3}(?:\.\d{1,3}){3}:)?(?P<port>\d{2,5}):\d{2,5}["']?\s*$"""
    )

    for config_name in (".env", "docker-compose.yml"):
        config_path = os.path.join(project_path, config_name)
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                content = file.read(262144)
        except OSError:
            continue

        for match in port_variable_pattern.finditer(content):
            value = int(match.group("port"))
            port_key = (match.group("label"), value)
            if 0 < value <= 65535 and port_key not in seen_ports:
                seen_ports.add(port_key)
                ports.append({"label": match.group("label"), "value": value})

        if config_name == "docker-compose.yml":
            for match in port_default_pattern.finditer(content):
                value = int(match.group("port"))
                port_key = (match.group("label"), value)
                if 0 < value <= 65535 and port_key not in seen_ports:
                    seen_ports.add(port_key)
                    ports.append({"label": match.group("label"), "value": value})

            for match in compose_port_pattern.finditer(content):
                value = int(match.group("port"))
                port_key = ("Docker", value)
                if 0 < value <= 65535 and port_key not in seen_ports:
                    seen_ports.add(port_key)
                    ports.append({"label": "Docker", "value": value})

    return {
        "branch": branch or "No branch",
        "stack": stack or [{"name": "Unclassified", "icons": []}],
        "ports": ports,
    }


def scan_workspace_projects():
    workspace_root = os.path.abspath(os.path.expanduser("~/garage/workspaces"))
    projects = []

    try:
        entries = sorted(os.scandir(workspace_root), key=lambda entry: entry.name.lower())
    except OSError:
        return projects

    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue

        project_path = os.path.abspath(entry.path)
        brain_path = os.path.join(project_path, ".nexus", "brain.md")
        summary = "No generated workspace summary is available."

        try:
            with open(brain_path, "r", encoding="utf-8") as file:
                content = " ".join(
                    line.strip()
                    for line in file
                    if line.strip() and line.strip() != "---"
                )
            if content:
                summary = content[:197].rstrip()
                if len(content) > 197:
                    summary = f"{summary}..."
        except OSError:
            pass

        projects.append(
            {
                "name": entry.name,
                "path": project_path,
                "summary": summary,
                **get_project_metadata(project_path),
            }
        )

    return projects


def attach_project_telemetry(projects):
    totals_by_path = {
        os.path.realpath(project["path"]): {
            "memory_bytes": 0,
            "cpu_percent": 0.0,
            "process_count": 0,
        }
        for project in projects
    }

    try:
        processes = psutil.process_iter(["cwd", "memory_info", "cpu_percent"])
        for process in processes:
            try:
                cwd = process.info.get("cwd")
                totals = totals_by_path.get(os.path.realpath(cwd)) if cwd else None
                if totals is None:
                    continue

                memory_info = process.info.get("memory_info")
                totals["memory_bytes"] += memory_info.rss if memory_info else 0
                totals["cpu_percent"] += process.info.get("cpu_percent") or 0.0
                totals["process_count"] += 1
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass

    for project in projects:
        totals = totals_by_path[os.path.realpath(project["path"])]
        project["telemetry"] = {
            "running": totals["process_count"] > 0,
            "process_count": totals["process_count"],
            "ram_mb": round(totals["memory_bytes"] / (1024 * 1024), 1),
            "cpu_percent": round(totals["cpu_percent"], 1),
        }

    return projects


def get_server_health():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    network_interfaces = psutil.net_io_counters(pernic=True)
    network_candidates = [
        (name, counters)
        for name, counters in network_interfaces.items()
        if name != "lo"
    ]
    selected_network = None

    if "tailscale0" in network_interfaces:
        selected_name = "tailscale0"
        selected_network = network_interfaces[selected_name]
        network_type = "tailscale"
    elif network_candidates:
        selected_name, selected_network = max(
            network_candidates,
            key=lambda item: item[1].bytes_sent + item[1].bytes_recv,
        )
        network_type = "standard"
    else:
        selected_name = None
        network_type = "unavailable"

    interface_data = [
        {
            "name": name,
            "type": "tailscale" if name == "tailscale0" else "standard",
            "bytes_sent": counters.bytes_sent,
            "bytes_recv": counters.bytes_recv,
        }
        for name, counters in network_interfaces.items()
        if name != "lo"
    ]

    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "description": platform.platform(),
        },
        "boot_time": psutil.boot_time(),
        "cpu": {
            "cores": psutil.cpu_percent(percpu=True),
            "logical_count": psutil.cpu_count(logical=True),
        },
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "used": memory.used,
            "percent": memory.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "network": {
            "interface": selected_name,
            "type": network_type,
            "bytes_sent": selected_network.bytes_sent if selected_network else 0,
            "bytes_recv": selected_network.bytes_recv if selected_network else 0,
            "interfaces": interface_data,
        },
    }


def list_workspace_processes(workspace_path):
    active_path = os.path.realpath(workspace_path)
    resources = []

    for process in psutil.process_iter(
        ["pid", "name", "cwd", "memory_percent", "cpu_percent"]
    ):
        try:
            cwd = process.info.get("cwd")
            if not cwd or os.path.realpath(cwd) != active_path:
                continue
            resources.append(
                {
                    "pid": process.info["pid"],
                    "name": process.info.get("name") or "Unknown",
                    "cwd": cwd,
                    "memory_percent": process.info.get("memory_percent") or 0,
                    "cpu_percent": process.info.get("cpu_percent") or 0,
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

    return resources


def serialize_task(task):
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def serialize_footprint(footprint):
    return {
        "id": footprint.id,
        "workspace_id": footprint.workspace_id,
        "persona": footprint.persona,
        "action_type": footprint.action_type,
        "content": footprint.content,
        "created_at": footprint.created_at.isoformat() if footprint.created_at else None,
    }


def serialize_message(message):
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def save_footprints(footprints):
    db_context = get_db()
    db = next(db_context)
    try:
        db.add_all(footprints)
        db.commit()
        for footprint in footprints:
            db.refresh(footprint)
        return footprints
    except Exception:
        db.rollback()
        raise
    finally:
        db_context.close()


def get_workspace_id(local_path):
    db_context = get_db()
    db = next(db_context)
    try:
        workspace = db.execute(
            select(Workspace).where(Workspace.local_path == os.path.abspath(local_path))
        ).scalar_one_or_none()
        return workspace.id if workspace is not None else None
    finally:
        db_context.close()


def get_known_user_preferences():
    db_context = get_db()
    db = next(db_context)
    try:
        profiles = db.execute(
            select(UserProfile).order_by(UserProfile.preference_key.asc())
        ).scalars().all()
        return "\n".join(
            f"- {profile.preference_key}: {profile.preference_value}"
            for profile in profiles
        )
    finally:
        db_context.close()


def persist_architect_diagram(workspace_path, response_text):
    diagrams = re.findall(
        r"```mermaid\s*(.*?)```",
        response_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not diagrams:
        return False

    diagram = diagrams[-1].strip()
    if not diagram:
        return False

    architecture_dir = os.path.abspath(os.path.join(workspace_path, ".nexus"))
    architecture_path = os.path.join(architecture_dir, "architecture.mmd")
    try:
        os.makedirs(architecture_dir, exist_ok=True)
        with open(architecture_path, "w", encoding="utf-8") as file:
            file.write(diagram)
    except OSError:
        return False

    return True


def extract_tech_lead_tasks(response_text):
    task_pattern = re.compile(
        r"(?ms)^\s*\d+[.)]\s*(?:Task:\s*)?(?P<title>[^\r\n]+)\r?\n"
        r"(?P<body>.*?)(?=^\s*\d+[.)]\s*(?:Task:\s*)?|\Z)"
    )
    codex_pattern = re.compile(
        r'(?m)^\s*(?P<command>codex\s+"(?:\\.|[^"\\])*")\s*$'
    )
    tasks = []

    for match in task_pattern.finditer(response_text):
        command_match = codex_pattern.search(match.group("body"))
        if command_match is None:
            continue

        title = match.group("title").strip()
        description = match.group("body").strip()
        if not title or not description:
            continue

        tasks.append(
            {
                "title": title[:255],
                "description": description,
                "command": command_match.group("command"),
            }
        )

    return tasks


def save_tech_lead_tasks(workspace_id, response_text):
    extracted_tasks = extract_tech_lead_tasks(response_text)
    if not extracted_tasks:
        return []

    db_context = get_db()
    db = next(db_context)
    try:
        tasks = [
            Task(
                workspace_id=workspace_id,
                title=task["title"],
                description=task["description"],
                status="todo",
            )
            for task in extracted_tasks
        ]
        db.add_all(tasks)
        db.commit()
        return tasks
    except Exception:
        db.rollback()
        raise
    finally:
        db_context.close()


def bind_cto_chat_session(workspace_id):
    session_id = f"cto_workspace_{workspace_id}"
    db_context = get_db()
    db = next(db_context)
    try:
        chat_session = db.get(ChatSession, session_id)
        if chat_session is None:
            chat_session = ChatSession(
                id=session_id,
                workspace_id=workspace_id,
                active_persona="cto",
            )
            db.add(chat_session)
        else:
            chat_session.workspace_id = workspace_id
            chat_session.active_persona = "cto"
        db.commit()
        return session_id
    except Exception:
        db.rollback()
        raise
    finally:
        db_context.close()


def extract_first_codex_command_from_text(text):
    if not isinstance(text, str) or not text:
        return None

    try:
        commands = extract_codex_commands(text)
    except Exception:
        return None

    return commands[0] if commands else None


def _prompt_from_codex_command(command):
    try:
        arguments = shlex.split(command or "")
    except ValueError:
        return None
    if len(arguments) != 2 or arguments[0] != "codex":
        return None
    return arguments[1]


def _safe_create_factory_event(db, workspace_id, event_type, message, **kwargs):
    try:
        return create_factory_event(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            message=message,
            **kwargs,
        )
    except Exception as exception:
        try:
            db.rollback()
        except Exception:
            pass
        print("Factory event creation failed: {}".format(exception))
        return None


def _safe_db_commit(db):
    if not hasattr(db, "commit"):
        return False
    db.commit()
    return True


def _safe_db_refresh(db, obj):
    if not hasattr(db, "refresh"):
        return False
    db.refresh(obj)
    return True


def _send_factory_discord_notification(message):
    # TODO: Wire this to the existing Discord notifier once it can be tested
    # without network access. Factory run recording must never depend on Discord.
    return False


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _preflight_status_file(workspace_path):
    return os.path.join(os.path.abspath(workspace_path), PREFLIGHT_STATUS_PATH)


def _preflight_workflow_file(workspace_path):
    return os.path.join(os.path.abspath(workspace_path), PREFLIGHT_WORKFLOW_PATH)


def _redact_preflight_output(text):
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    excerpt = text[-PREFLIGHT_OUTPUT_EXCERPT_CHARS:]
    return SECRET_TEXT_PATTERN.sub("[redacted]", excerpt)


def _read_local_preflight_record(workspace_path):
    status_path = _preflight_status_file(workspace_path)
    try:
        with open(status_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_local_preflight_record(workspace_path, record):
    status_path = _preflight_status_file(workspace_path)
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    with open(status_path, "w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=True, indent=2, sort_keys=True)


def _build_preflight_status(workspace_path, run_active=False):
    record = _read_local_preflight_record(workspace_path)
    workflow_present = os.path.exists(_preflight_workflow_file(workspace_path))
    return {
        "workflow_present": workflow_present,
        "workflow_path": PREFLIGHT_WORKFLOW_PATH,
        "local_last_result": record.get("result") or "unknown",
        "local_last_run_at": record.get("finished_at"),
        "local_last_duration_seconds": record.get("duration_seconds"),
        "local_last_output_excerpt": record.get("output_excerpt") or "",
        "local_last_returncode": record.get("returncode"),
        "run_active": bool(run_active),
        "quick_command": " ".join(PREFLIGHT_QUICK_COMMAND),
        "strict_ci_command": " ".join(PREFLIGHT_STRICT_CI_COMMAND),
    }


def _run_local_quick_preflight(workspace_path):
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    stdout = ""
    stderr = ""
    returncode = -1
    timed_out = False
    error_message = ""

    try:
        result = subprocess.run(
            PREFLIGHT_QUICK_COMMAND,
            cwd=os.path.abspath(workspace_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        returncode = result.returncode
    except subprocess.TimeoutExpired as exception:
        timed_out = True
        stdout = exception.stdout or ""
        stderr = exception.stderr or ""
        returncode = -1
        error_message = "Local quick preflight timed out after {} seconds.".format(PREFLIGHT_TIMEOUT_SECONDS)
    except OSError as exception:
        stderr = str(exception)
        returncode = -1
        error_message = str(exception)

    finished_at = _utc_now_iso()
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    output_excerpt = _redact_preflight_output("\n".join([stdout, stderr]).strip())
    result_label = "pass" if returncode == 0 and "NEXUS_PREFLIGHT_RESULT=PASS" in stdout else "fail"
    if timed_out:
        result_label = "fail"

    record = {
        "result": result_label,
        "returncode": returncode,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "stdout_excerpt": _redact_preflight_output(stdout),
        "stderr_excerpt": _redact_preflight_output(stderr),
        "output_excerpt": output_excerpt,
        "timed_out": timed_out,
        "error": error_message,
        "command": list(PREFLIGHT_QUICK_COMMAND),
    }
    _write_local_preflight_record(workspace_path, record)
    return record


def _execute_factory_task(
    db,
    workspace,
    task,
    execution_mode,
    work_packet_id=None,
    create_requested_event=True,
):
    workspace_id = workspace.id
    task_id = task.id
    workspace_path = os.path.abspath(workspace.local_path)
    task_title = getattr(task, "title", None) or "Task #{}".format(task_id)
    task_description = task.description or ""
    factory_events_created = 0

    if not os.path.isdir(workspace_path):
        return {
            "status": "failed",
            "message": "Workspace directory not found.",
            "status_code": 400,
            "task_status": getattr(task, "status", None),
            "execution_run_id": None,
            "factory_events_created": 0,
            "git": {},
            "stdout": "",
            "stderr": "Workspace directory not found.",
            "returncode": -1,
            "timeout_seconds": 0,
            "execution_time": 0,
            "token_usage": {},
        }

    commands = extract_codex_commands(task_description)
    if len(commands) != 1:
        return {
            "status": "failed",
            "message": "Task description must contain exactly one codex command.",
            "status_code": 400,
            "task_status": getattr(task, "status", None),
            "execution_run_id": None,
            "factory_events_created": 0,
            "git": {},
            "stdout": "",
            "stderr": "Task description must contain exactly one codex command.",
            "returncode": -1,
            "timeout_seconds": 0,
            "execution_time": 0,
            "token_usage": {},
        }

    command_prompt = _prompt_from_codex_command(commands[0])
    if command_prompt is None or not command_prompt.strip():
        return {
            "status": "failed",
            "message": "Task codex command is invalid.",
            "status_code": 400,
            "task_status": getattr(task, "status", None),
            "execution_run_id": None,
            "factory_events_created": 0,
            "git": {},
            "stdout": "",
            "stderr": "Task codex command is invalid.",
            "returncode": -1,
            "timeout_seconds": 0,
            "execution_time": 0,
            "token_usage": {},
        }

    if create_requested_event:
        event = _safe_create_factory_event(
            db,
            workspace_id,
            "task_run_requested",
            "Run requested for task: {}".format(task_title),
            work_packet_id=work_packet_id,
            task_id=task_id,
            payload={"execution_mode": execution_mode, "command_excerpt": commands[0][:240]},
        )
        factory_events_created += 1 if event is not None else 0

    started_at = datetime.now(timezone.utc)
    execution_run = ExecutionRun(
        workspace_id=workspace_id,
        work_packet_id=work_packet_id,
        task_id=task_id,
        command=commands[0],
        prompt=command_prompt,
        status="running",
        started_at=started_at,
        provider="codex",
        model="codex-cli",
    )
    if hasattr(db, "add"):
        db.add(execution_run)
        _safe_db_commit(db)
        _safe_db_refresh(db, execution_run)

    event = _safe_create_factory_event(
        db,
        workspace_id,
        "task_run_started",
        "Codex run started for task: {}".format(task_title),
        work_packet_id=work_packet_id,
        task_id=task_id,
        execution_run_id=execution_run.id,
        payload={"execution_mode": execution_mode, "command_excerpt": commands[0][:240]},
    )
    factory_events_created += 1 if event is not None else 0
    _send_factory_discord_notification("Run One Task started: {}".format(task_title))

    try:
        codex_result = CodexRunner(timeout_factory=calculate_prompt_timeout).run(
            command_prompt,
            workspace_path,
            task_id=task_id,
        )
    except OSError as exception:
        finished_at = datetime.now(timezone.utc)
        execution_run.status = "failed"
        execution_run.returncode = -1
        execution_run.stdout = ""
        execution_run.stderr = str(exception)
        execution_run.finished_at = finished_at
        execution_run.duration_seconds = (finished_at - started_at).total_seconds()
        execution_run.timeout_seconds = 0
        execution_run.error_message = str(exception)
        task.status = "review"
        _safe_db_commit(db)
        event = _safe_create_factory_event(
            db,
            workspace_id,
            "codex_run_failed",
            "Codex runner failed before execution for task: {}".format(task_title),
            work_packet_id=work_packet_id,
            task_id=task_id,
            execution_run_id=execution_run.id,
            payload={"error": str(exception)},
        )
        factory_events_created += 1 if event is not None else 0
        event = _safe_create_factory_event(
            db,
            workspace_id,
            "task_marked_review_required",
            "Task moved to review after failure: {}".format(task_title),
            work_packet_id=work_packet_id,
            task_id=task_id,
            execution_run_id=execution_run.id,
        )
        factory_events_created += 1 if event is not None else 0
        _send_factory_discord_notification("Run One Task failed: {}".format(task_title))
        return {
            "status": "failed",
            "message": str(exception),
            "status_code": 500,
            "task_status": task.status,
            "execution_run_id": execution_run.id,
            "factory_events_created": factory_events_created,
            "git": summarize_git_changes(workspace_path),
            "stdout": "",
            "stderr": str(exception),
            "returncode": -1,
            "timeout_seconds": 0,
            "execution_time": execution_run.duration_seconds,
            "token_usage": {},
        }

    status = "success"
    status_code = 200
    event_type = "codex_run_completed"
    if codex_result.status == "timeout":
        status = "timeout"
        status_code = 504
        event_type = "codex_run_timeout"
    elif codex_result.status != "success" or codex_result.returncode != 0:
        status = "failed"
        status_code = 500
        event_type = "codex_run_failed"

    token_usage = codex_result.token_usage or {}
    finished_at = datetime.now(timezone.utc)
    execution_run.status = status
    execution_run.returncode = codex_result.returncode
    execution_run.stdout = codex_result.stdout
    execution_run.stderr = codex_result.stderr
    execution_run.finished_at = finished_at
    execution_run.duration_seconds = codex_result.execution_time
    execution_run.timeout_seconds = codex_result.timeout_seconds
    execution_run.input_tokens = token_usage.get("input_tokens")
    execution_run.output_tokens = token_usage.get("output_tokens")
    execution_run.total_tokens = token_usage.get("total_tokens")
    execution_run.estimated_cost_usd = token_usage.get("estimated_cost_usd")
    if status == "timeout":
        execution_run.error_message = "Codex execution timed out after {} seconds.".format(
            codex_result.timeout_seconds
        )
        task.status = "review"
    elif status == "failed":
        execution_run.error_message = (
            (codex_result.stderr or "").strip()
            or (codex_result.stdout or "").strip()
            or "Codex execution failed."
        )
        task.status = "review"
    else:
        task.status = "done"
    _safe_db_commit(db)

    event = _safe_create_factory_event(
        db,
        workspace_id,
        event_type,
        "Codex run {} for task: {}".format(status, task_title),
        work_packet_id=work_packet_id,
        task_id=task_id,
        execution_run_id=execution_run.id,
        payload={
            "returncode": codex_result.returncode,
            "duration_seconds": codex_result.execution_time,
            "token_usage": token_usage,
        },
    )
    factory_events_created += 1 if event is not None else 0

    git_summary = summarize_git_changes(workspace_path)
    changed_files = git_summary.get("changed_files", [])
    changed_file_rows = []
    for changed_file in changed_files:
        changed_file_rows.append(
            ExecutionChangedFile(
                execution_run_id=execution_run.id,
                file_path=changed_file.get("path") or "",
                change_type=changed_file.get("status") or "",
                insertions=0,
                deletions=0,
                diff_summary=git_summary.get("diff_stat") or git_summary.get("status_output") or "",
            )
        )
    if changed_file_rows and hasattr(db, "add_all"):
        db.add_all(changed_file_rows)
        _safe_db_commit(db)

    event = _safe_create_factory_event(
        db,
        workspace_id,
        "git_changes_captured",
        "Captured {} changed file{} after task run.".format(
            len(changed_files),
            "" if len(changed_files) == 1 else "s",
        ),
        work_packet_id=work_packet_id,
        task_id=task_id,
        execution_run_id=execution_run.id,
        payload={
            "changed_files": changed_files,
            "is_dirty": git_summary.get("is_dirty", False),
        },
    )
    factory_events_created += 1 if event is not None else 0

    final_task_event_type = "task_marked_done" if task.status == "done" else "task_marked_review_required"
    event = _safe_create_factory_event(
        db,
        workspace_id,
        final_task_event_type,
        "Task moved to {}: {}".format(task.status, task_title),
        work_packet_id=work_packet_id,
        task_id=task_id,
        execution_run_id=execution_run.id,
        payload={"task_status": task.status},
    )
    factory_events_created += 1 if event is not None else 0

    if token_usage:
        cost_event = {
            "source": "run_one" if work_packet_id is None else "packet_runner",
            "provider": "codex",
            "model": "codex-cli",
            "task_id": task_id,
            "notes": "One-task Codex execution." if work_packet_id is None else "Supervised packet task execution.",
        }
        for key in ("total_tokens", "input_tokens", "output_tokens", "estimated_cost_usd"):
            if key in token_usage:
                cost_event[key] = token_usage.get(key)
        try:
            append_cost_event(workspace_path, cost_event)
        except OSError:
            pass

    _send_factory_discord_notification(
        "Run One Task {}: {} | {:.2f}s | {} tokens | {} changed files".format(
            status,
            task_title,
            codex_result.execution_time or 0,
            token_usage.get("total_tokens", 0),
            len(changed_files),
        )
    )

    return {
        "status": status,
        "status_code": status_code,
        "task_status": task.status,
        "execution_run_id": execution_run.id,
        "factory_events_created": factory_events_created,
        "git": git_summary,
        "stdout": codex_result.stdout,
        "stderr": codex_result.stderr,
        "returncode": codex_result.returncode,
        "timeout_seconds": codex_result.timeout_seconds,
        "execution_time": codex_result.execution_time,
        "token_usage": token_usage,
    }


class AutonomousQueue:
    POLL_INTERVAL_SECONDS = 2
    COMPLETION_TIMEOUT_SECONDS = 120
    CODEX_COMMAND_PATTERN = re.compile(r'codex\s+"(?:\\.|[^"\\])*"')

    def __init__(self):
        self._lock = Lock()
        self._thread = None
        self._state = {
            "running": False,
            "state": "idle",
            "workspace_id": None,
            "current_task_id": None,
            "current_task_title": None,
            "completed": 0,
            "total": 0,
            "message": "Auto-Pilot is idle.",
        }

    @staticmethod
    def is_configured():
        return bool((os.getenv("DISCORD_WEBHOOK_URL") or "").strip())

    def status(self):
        with self._lock:
            return dict(self._state)

    def start(self, workspace_id, workspace_path):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False, dict(self._state)

            self._state = {
                "running": True,
                "state": "starting",
                "workspace_id": workspace_id,
                "current_task_id": None,
                "current_task_title": None,
                "completed": 0,
                "total": 0,
                "message": "Auto-Pilot is preparing the task queue.",
            }
            self._thread = Thread(
                target=self._run,
                args=(workspace_id, workspace_path),
                name=f"autonomous-queue-{workspace_id}",
                daemon=True,
            )
            self._thread.start()
            return True, dict(self._state)

    def _set_state(self, **updates):
        with self._lock:
            self._state.update(updates)

    def _send_discord(self, message):
        webhook_url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
        if not webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URL is not configured.")

        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=10,
        )
        response.raise_for_status()

    @staticmethod
    def _todo_tasks(workspace_id):
        db_context = get_db()
        db = next(db_context)
        try:
            tasks = db.execute(
                select(Task)
                .where(
                    Task.workspace_id == workspace_id,
                    Task.status == "todo",
                )
                .order_by(Task.created_at.asc(), Task.id.asc())
            ).scalars().all()
            return [
                {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                }
                for task in tasks
            ]
        finally:
            db_context.close()

    @staticmethod
    def _task_status(workspace_id, task_id):
        db_context = get_db()
        db = next(db_context)
        try:
            task = db.get(Task, task_id)
            if task is None or task.workspace_id != workspace_id:
                return None
            return task.status
        finally:
            db_context.close()

    @classmethod
    def _codex_prompt(cls, description):
        command_match = cls.CODEX_COMMAND_PATTERN.search(description or "")
        if command_match is None:
            raise ValueError("Task does not contain a valid codex command.")

        arguments = shlex.split(command_match.group(0))
        if len(arguments) != 2 or arguments[0] != "codex":
            raise ValueError("Task codex command format is invalid.")
        return arguments[1]

    @staticmethod
    def _write_crash_log(workspace_path, exception, stdout="", stderr=""):
        def as_text(output):
            if isinstance(output, bytes):
                return output.decode("utf-8", errors="replace")
            return output or ""

        crash_log_path = os.path.join(workspace_path, "autopilot_crash.log")
        with open(crash_log_path, "w", encoding="utf-8") as file:
            file.write(f"exception_type: {type(exception).__name__}\n")
            file.write(f"exception: {exception!r}\n\n")
            file.write("stdout:\n")
            file.write(as_text(stdout))
            file.write("\n\nstderr:\n")
            file.write(as_text(stderr))
            file.write("\n")

    @classmethod
    def _execute_codex(cls, task, workspace_path):
        prompt = cls._codex_prompt(task["description"])
        result = CodexRunner(timeout_factory=calculate_prompt_timeout).run(
            prompt,
            workspace_path,
            task_id=task.get("id"),
        )

        if result.status == "timeout":
            error = "Codex execution timed out after {} seconds.".format(result.timeout_seconds)
            append_codex_telemetry(
                {
                    "task_id": task.get("id"),
                    "action": "codex_exec",
                    "execution_time": round(result.execution_time, 3),
                    "return_code": result.returncode,
                    "timeout_seconds": result.timeout_seconds,
                    "token_usage": result.token_usage,
                    "stderr": result.stderr,
                    "error": error,
                },
                base_dir=workspace_path,
            )
            exception = TimeoutError(error)
            cls._write_crash_log(
                workspace_path,
                exception,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            raise RuntimeError(error) from exception

        append_codex_telemetry(
            {
                "task_id": task.get("id"),
                "action": "codex_exec",
                "execution_time": round(result.execution_time, 3),
                "return_code": result.returncode,
                "timeout_seconds": result.timeout_seconds,
                "token_usage": result.token_usage,
                "stderr": result.stderr,
                "error": result.stderr if result.returncode != 0 else "",
            },
            base_dir=workspace_path,
        )

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "Codex execution failed."
            exception = RuntimeError(error)
            cls._write_crash_log(
                workspace_path,
                exception,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            raise exception

    def _run(self, workspace_id, workspace_path):
        current_task = None
        try:
            tasks = self._todo_tasks(workspace_id)
            self._set_state(total=len(tasks))

            for task in tasks:
                current_task = task
                if self._task_status(workspace_id, task["id"]) != "todo":
                    continue

                self._set_state(
                    state="running",
                    current_task_id=task["id"],
                    current_task_title=task["title"],
                    message=f"System Running: {task['title']}",
                )
                self._send_discord(f"🚀 Auto-Pilot Starting Task: {task['title']}")
                self._execute_codex(task, workspace_path)

                deadline = time.monotonic() + self.COMPLETION_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    task_status = self._task_status(workspace_id, task["id"])
                    if task_status == "done":
                        self._send_discord(f"✅ Task Completed: {task['title']}")
                        completed = self.status()["completed"] + 1
                        self._set_state(completed=completed)
                        break
                    if task_status is None:
                        raise RuntimeError("Task was deleted while Auto-Pilot was waiting for QA.")
                    time.sleep(self.POLL_INTERVAL_SECONDS)
                else:
                    raise TimeoutError("Timed out waiting for QA completion.")

            self._set_state(
                running=False,
                state="complete",
                current_task_id=None,
                current_task_title=None,
                message="Auto-Pilot completed all queued tasks.",
            )
        except Exception as exception:
            title = current_task["title"] if current_task else "Queue Startup"
            try:
                self._send_discord(f"❌ Error/Timeout on Task: {title}")
            except Exception:
                pass
            self._set_state(
                running=False,
                state="error",
                message=f"Auto-Pilot halted: {exception}",
            )


def start_workspace_watcher(engine, workspace_path):
    global active_watcher

    with active_watcher_lock:
        if active_watcher is not None:
            active_watcher.stop()
            active_watcher.join()
            active_watcher = None

        watcher = Observer()
        watcher.schedule(NexusWatcher(engine), os.path.abspath(workspace_path), recursive=True)
        watcher.start()
        active_watcher = watcher


class NexusDashboard:
    def __init__(self, engine):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.app = Flask(
            __name__,
            template_folder=os.path.join(base_dir, "templates"),
            static_folder=os.path.join(base_dir, "static"),
        )
        self.app.register_blueprint(projects_blueprint)
        self.engine = engine
        self.engine.telemetry_logger = append_codex_telemetry
        self.autonomous_queue = AutonomousQueue()
        self.packet_runner_lock = Lock()
        self.preflight_run_lock = Lock()
        self.preflight_run_active = False
        self.packet_runner_state = {
            "running": False,
            "mode": "one_packet",
            "work_packet_id": None,
            "current_task_id": None,
            "current_task_title": None,
            "completed": 0,
            "total": 0,
            "message": "Packet runner is idle.",
            "cancel_requested": False,
        }

        @self.app.route("/")
        def index():
            projects = attach_project_telemetry(scan_workspace_projects())
            return render_template("index.html", projects=projects)

        @self.app.route("/api/state")
        def get_state():
            return jsonify(self.engine.state)

        @self.app.route("/api/server-health", methods=["GET"])
        def server_health():
            return jsonify(get_server_health())

        @self.app.route("/api/resources", methods=["GET"])
        def get_resources():
            return jsonify(list_workspace_processes(self.engine.target_dir))

        @self.app.route("/api/telemetry", methods=["GET"])
        def get_telemetry():
            telemetry_path = os.path.abspath(
                os.path.join(self.engine.target_dir, ".nexus", "codex_telemetry.jsonl")
            )
            try:
                with open(telemetry_path, "r", encoding="utf-8") as file:
                    lines = list(deque(file, maxlen=50))
            except FileNotFoundError:
                lines = []
            except OSError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 500

            return jsonify({"status": "success", "logs": [line.rstrip("\n") for line in lines]})

        @self.app.route("/api/cost-ledger", methods=["GET"])
        def get_cost_ledger():
            events = read_cost_events(self.engine.target_dir, limit=100)
            return jsonify(
                {
                    "status": "success",
                    "events": events,
                    "summary": summarize_cost_events(events),
                }
            )

        @self.app.route("/api/cost-ledger/manual-entry", methods=["POST"])
        def create_manual_cost_entry():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "JSON object is required."}), 400

            allowed_fields = set(MANUAL_COST_TEXT_FIELDS) | {
                "total_tokens",
                "estimated_cost_usd",
            }
            if any(field not in allowed_fields for field in payload):
                return jsonify({"status": "error", "message": "Unsupported field present."}), 400

            event = {"source": "manual"}
            text_limits = {
                "provider": 100,
                "model": 120,
                "source": 80,
                "task_id": 80,
                "notes": 1000,
            }
            for field in MANUAL_COST_TEXT_FIELDS:
                value, error = _safe_manual_cost_text(payload, field, text_limits[field])
                if error:
                    return jsonify({"status": "error", "message": error}), 400
                if value is not None:
                    event[field] = value

            total_tokens, error = _safe_manual_cost_int(payload, "total_tokens")
            if error:
                return jsonify({"status": "error", "message": error}), 400
            if total_tokens is not None:
                event["total_tokens"] = total_tokens

            estimated_cost_usd, error = _safe_manual_cost_float(
                payload, "estimated_cost_usd"
            )
            if error:
                return jsonify({"status": "error", "message": error}), 400
            if estimated_cost_usd is not None:
                event["estimated_cost_usd"] = estimated_cost_usd

            if total_tokens is None and estimated_cost_usd is None:
                return jsonify(
                    {
                        "status": "error",
                        "message": "total_tokens or estimated_cost_usd is required.",
                    }
                ), 400

            try:
                append_cost_event(self.engine.target_dir, event)
                events = read_cost_events(self.engine.target_dir, limit=100)
            except OSError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 500

            return jsonify(
                {
                    "status": "success",
                    "summary": summarize_cost_events(events),
                }
            ), 201

        @self.app.route("/api/factory/status", methods=["GET"])
        def get_factory_status():
            git_summary = summarize_git_changes(self.engine.target_dir)
            ci_summary = summarize_ci_status(self.engine.target_dir)
            workspace_id = None
            try:
                workspace_id = get_workspace_id(self.engine.target_dir)
                db_context = get_db()
                db = next(db_context)
                try:
                    events = get_recent_factory_events(db, workspace_id=workspace_id, limit=100)
                    runs = get_recent_execution_runs(db, workspace_id=workspace_id, limit=50)
                finally:
                    db_context.close()
            except Exception as exception:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Factory database unavailable: {}".format(exception),
                        "git": git_summary,
                        "ci": ci_summary,
                    }
                ), 503

            state = summarize_factory_state(events, runs)
            with self.packet_runner_lock:
                runner_state = dict(self.packet_runner_state)
            return jsonify(
                {
                    "status": "success",
                    "factory": {
                        "execution_mode": self.engine.get_execution_mode(),
                        "automatic_analysis_enabled": self.engine.is_automatic_analysis_enabled(),
                        "current_state": state.get("current_state", "idle"),
                        "recent_event_count": state.get("recent_event_count", 0),
                        "recent_run_count": state.get("recent_run_count", 0),
                        "runner": runner_state,
                    },
                    "git": git_summary,
                    "ci": ci_summary,
                    "recent_events": [serialize_factory_event(event) for event in events],
                    "recent_runs": [serialize_execution_run(run) for run in runs],
                }
            )

        @self.app.route("/api/factory/events", methods=["GET"])
        def get_factory_events():
            limit = request.args.get("limit", default=100, type=int)
            try:
                workspace_id = get_workspace_id(self.engine.target_dir)
                db_context = get_db()
                db = next(db_context)
                try:
                    events = get_recent_factory_events(db, workspace_id=workspace_id, limit=limit)
                finally:
                    db_context.close()
            except Exception as exception:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Factory events unavailable: {}".format(exception),
                    }
                ), 503

            return jsonify(
                {
                    "status": "success",
                    "events": [serialize_factory_event(event) for event in events],
                }
            )

        @self.app.route("/api/factory/runs", methods=["GET"])
        def get_factory_runs():
            limit = request.args.get("limit", default=50, type=int)
            try:
                workspace_id = get_workspace_id(self.engine.target_dir)
                db_context = get_db()
                db = next(db_context)
                try:
                    runs = get_recent_execution_runs(db, workspace_id=workspace_id, limit=limit)
                finally:
                    db_context.close()
            except Exception as exception:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Factory runs unavailable: {}".format(exception),
                    }
                ), 503

            return jsonify(
                {
                    "status": "success",
                    "runs": [serialize_execution_run(run) for run in runs],
                }
            )

        @self.app.route("/api/factory/runs/<int:run_id>", methods=["GET"])
        def get_factory_run_details(run_id):
            try:
                active_workspace_id = get_workspace_id(self.engine.target_dir)
                db_context = get_db()
                db = next(db_context)
                try:
                    run = db.get(ExecutionRun, run_id)
                    if run is None or run.workspace_id != active_workspace_id:
                        return jsonify({"status": "error", "message": "Execution run not found."}), 404
                    task = db.get(Task, run.task_id) if run.task_id else None
                    changed_files = (
                        db.execute(
                            select(ExecutionChangedFile)
                            .where(ExecutionChangedFile.execution_run_id == run_id)
                            .order_by(ExecutionChangedFile.id.asc())
                        )
                        .scalars()
                        .all()
                    )
                    events = (
                        db.execute(
                            select(FactoryEvent)
                            .where(FactoryEvent.execution_run_id == run_id)
                            .order_by(FactoryEvent.created_at.desc(), FactoryEvent.id.desc())
                        )
                        .scalars()
                        .all()
                    )
                finally:
                    db_context.close()
            except Exception as exception:
                return jsonify({"status": "error", "message": "Run details unavailable: {}".format(exception)}), 503

            return jsonify(
                {
                    "status": "success",
                    "run": serialize_execution_run(run),
                    "task": serialize_task(task) if task is not None else None,
                    "changed_files": [serialize_changed_file(changed_file) for changed_file in changed_files],
                    "events": [serialize_factory_event(event) for event in events],
                }
            )

        @self.app.route("/api/factory/git-status", methods=["GET"])
        def get_factory_git_status():
            return jsonify(
                {
                    "status": "success",
                    "git": summarize_git_changes(self.engine.target_dir),
                }
            )

        @self.app.route("/api/factory/ci-status", methods=["GET"])
        def get_factory_ci_status():
            return jsonify(
                {
                    "status": "success",
                    "ci": summarize_ci_status(self.engine.target_dir),
                }
            )

        @self.app.route("/api/factory/preflight/status", methods=["GET"])
        def get_factory_preflight_status():
            with self.preflight_run_lock:
                run_active = self.preflight_run_active
            return jsonify(
                {
                    "status": "success",
                    "preflight": _build_preflight_status(self.engine.target_dir, run_active=run_active),
                }
            )

        @self.app.route("/api/factory/preflight/run", methods=["POST"])
        def run_factory_preflight():
            with self.preflight_run_lock:
                if self.preflight_run_active:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Local quick preflight is already running.",
                            "preflight": _build_preflight_status(self.engine.target_dir, run_active=True),
                        }
                    ), 409
                self.preflight_run_active = True

            try:
                record = _run_local_quick_preflight(self.engine.target_dir)
                event_type = "preflight_run_completed" if record.get("result") == "pass" else "preflight_run_failed"
                try:
                    workspace_id = get_workspace_id(self.engine.target_dir)
                    if workspace_id is not None:
                        db_context = get_db()
                        db = next(db_context)
                        try:
                            _safe_create_factory_event(
                                db,
                                workspace_id,
                                event_type,
                                "Local quick preflight {}.".format(record.get("result")),
                                payload={
                                    "returncode": record.get("returncode"),
                                    "duration_seconds": record.get("duration_seconds"),
                                    "command": record.get("command"),
                                },
                            )
                        finally:
                            db_context.close()
                except Exception:
                    pass

                status_code = 200 if record.get("result") == "pass" else 500
                return jsonify(
                    {
                        "status": "success" if record.get("result") == "pass" else "error",
                        "preflight": _build_preflight_status(self.engine.target_dir, run_active=False),
                        "result": record,
                    }
                ), status_code
            finally:
                with self.preflight_run_lock:
                    self.preflight_run_active = False

        @self.app.route("/api/factory/events/manual", methods=["POST"])
        def create_manual_factory_event():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "JSON object is required."}), 400

            event_type = payload.get("event_type") or "manual_note"
            message = payload.get("message")
            event_payload = payload.get("payload")
            if not isinstance(event_type, str) or not event_type.strip():
                return jsonify({"status": "error", "message": "event_type is required."}), 400
            if len(event_type.strip()) > 64:
                return jsonify({"status": "error", "message": "event_type is too long."}), 400
            if not isinstance(message, str) or not message.strip():
                return jsonify({"status": "error", "message": "message is required."}), 400
            if len(message.strip()) > 2000:
                return jsonify({"status": "error", "message": "message is too long."}), 400
            if event_payload is not None and not isinstance(event_payload, (dict, list)):
                return jsonify({"status": "error", "message": "payload must be an object or array."}), 400

            try:
                workspace_id = get_workspace_id(self.engine.target_dir)
                if workspace_id is None:
                    return jsonify({"status": "error", "message": "Active workspace not found."}), 400

                db_context = get_db()
                db = next(db_context)
                try:
                    event = create_factory_event(
                        db,
                        workspace_id=workspace_id,
                        event_type=event_type.strip(),
                        message=message.strip(),
                        payload=event_payload,
                    )
                finally:
                    db_context.close()
            except Exception as exception:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Factory event could not be recorded: {}".format(exception),
                    }
                ), 503

            return jsonify({"status": "success", "event": serialize_factory_event(event)}), 201

        @self.app.route("/api/kill-process", methods=["POST"])
        def kill_process():
            payload = request.json or {}
            pid = payload.get("pid")

            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                return jsonify({"status": "error", "message": "Valid pid is required."}), 400

            if pid == os.getpid():
                return jsonify(
                    {"status": "error", "message": "The dashboard process cannot terminate itself."}
                ), 400

            try:
                process = psutil.Process(pid)
                cwd = process.cwd()
            except psutil.NoSuchProcess:
                return jsonify({"status": "error", "message": "Process not found."}), 404
            except psutil.AccessDenied:
                return jsonify({"status": "error", "message": "Process access denied."}), 403

            if os.path.realpath(cwd) != os.path.realpath(self.engine.target_dir):
                return jsonify(
                    {"status": "error", "message": "Process is outside the active workspace."}
                ), 403

            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return jsonify({"status": "error", "message": "Process not found."}), 404
            except PermissionError:
                return jsonify({"status": "error", "message": "Process access denied."}), 403
            except OSError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 500

            return jsonify({"status": "success", "message": "Termination signal sent.", "pid": pid})

        @self.app.route("/api/portfolio", methods=["GET"])
        def get_portfolio():
            return jsonify(self.engine.get_global_portfolio())

        @self.app.route("/api/switch-project", methods=["POST"])
        def switch_project():
            payload = request.json or {}
            path = payload.get("path")

            if not isinstance(path, str) or not path.strip():
                return jsonify({"status": "error", "message": "Path is required."}), 400

            try:
                result = self.engine.change_target(path)
            except ValueError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                workspace = db.execute(
                    select(Workspace).where(Workspace.local_path == result["target_dir"])
                ).scalar_one_or_none()
                if workspace is None:
                    workspace = Workspace(
                        name=os.path.basename(result["target_dir"]) or result["target_dir"],
                        local_path=result["target_dir"],
                    )
                    db.add(workspace)
                    db.commit()
                    db.refresh(workspace)

                result["workspace_id"] = workspace.id
                workspace_path = workspace.local_path
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

            start_workspace_watcher(self.engine, workspace_path)
            return jsonify(result)

        @self.app.route("/api/write-file", methods=["POST"])
        def write_file():
            payload = request.json or {}
            file_path = payload.get("file_path")
            content = payload.get("content")

            if not isinstance(file_path, str) or not file_path.strip():
                return jsonify({"status": "error", "message": "File path is required."}), 400

            if not isinstance(content, str):
                return jsonify({"status": "error", "message": "Content must be a string."}), 400

            if os.path.isabs(file_path):
                return jsonify({"status": "error", "message": "Invalid file path."}), 400

            workspace_dir = os.path.realpath(self.engine.target_dir)
            destination = os.path.realpath(os.path.join(workspace_dir, file_path))

            try:
                is_within_workspace = (
                    destination != workspace_dir
                    and os.path.commonpath([workspace_dir, destination]) == workspace_dir
                )
            except ValueError:
                is_within_workspace = False

            if not is_within_workspace:
                return jsonify({"status": "error", "message": "Invalid file path."}), 400

            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with open(destination, "w", encoding="utf-8") as file:
                    file.write(content)
            except OSError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 500

            return jsonify(
                {
                    "status": "success",
                    "message": "File written successfully.",
                    "file_path": os.path.relpath(destination, workspace_dir),
                }
            )

        @self.app.route("/api/tasks", methods=["GET"])
        def get_tasks():
            workspace_id = request.args.get("workspace_id", type=int)
            if workspace_id is None:
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                tasks = db.execute(
                    select(Task)
                    .where(Task.workspace_id == workspace_id)
                    .order_by(Task.created_at.asc(), Task.id.asc())
                ).scalars().all()
                return jsonify([serialize_task(task) for task in tasks])
            finally:
                db_context.close()

        @self.app.route("/api/tasks", methods=["POST"])
        def create_task():
            payload = request.json or {}
            workspace_id = payload.get("workspace_id")
            title = payload.get("title")
            description = payload.get("description")

            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            if not isinstance(title, str) or not title.strip():
                return jsonify({"status": "error", "message": "Title is required."}), 400
            if not isinstance(description, str):
                return jsonify({"status": "error", "message": "Description must be a string."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                task = Task(
                    workspace_id=workspace_id,
                    title=title.strip(),
                    description=description,
                )
                db.add(task)
                db.commit()
                db.refresh(task)
                return jsonify(serialize_task(task)), 201
            except IntegrityError:
                db.rollback()
                return jsonify({"status": "error", "message": "Workspace not found."}), 400
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/tasks/<int:task_id>/factory-details", methods=["GET"])
        def get_task_factory_details(task_id):
            try:
                active_workspace_id = get_workspace_id(self.engine.target_dir)
                db_context = get_db()
                db = next(db_context)
                try:
                    task = db.get(Task, task_id)
                    if task is None or task.workspace_id != active_workspace_id:
                        return jsonify({"status": "error", "message": "Task not found."}), 404
                    runs = (
                        db.execute(
                            select(ExecutionRun)
                            .where(ExecutionRun.task_id == task_id)
                            .order_by(ExecutionRun.started_at.desc(), ExecutionRun.id.desc())
                        )
                        .scalars()
                        .all()
                    )
                    events = (
                        db.execute(
                            select(FactoryEvent)
                            .where(FactoryEvent.task_id == task_id)
                            .order_by(FactoryEvent.created_at.desc(), FactoryEvent.id.desc())
                        )
                        .scalars()
                        .all()
                    )
                    latest_run = runs[0] if runs else None
                    changed_files = []
                    if latest_run is not None:
                        changed_files = (
                            db.execute(
                                select(ExecutionChangedFile)
                                .where(ExecutionChangedFile.execution_run_id == latest_run.id)
                                .order_by(ExecutionChangedFile.id.asc())
                            )
                            .scalars()
                            .all()
                        )
                finally:
                    db_context.close()
            except Exception as exception:
                return jsonify({"status": "error", "message": "Task details unavailable: {}".format(exception)}), 503

            return jsonify(
                {
                    "status": "success",
                    "task": serialize_task(task),
                    "latest_runs": [serialize_execution_run(run) for run in runs[:10]],
                    "latest_events": [serialize_factory_event(event) for event in events[:20]],
                    "changed_files": [serialize_changed_file(changed_file) for changed_file in changed_files],
                }
            )

        @self.app.route("/api/tasks/<int:task_id>/mark-review-required", methods=["POST"])
        def mark_task_review_required(task_id):
            payload = request.get_json(silent=True) or {}
            workspace_id = payload.get("workspace_id")
            reason = payload.get("reason") or "Marked review required by operator."
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            if not isinstance(reason, str):
                return jsonify({"status": "error", "message": "reason must be a string."}), 400

            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403

            db_context = get_db()
            db = next(db_context)
            try:
                task = db.get(Task, task_id)
                if task is None or task.workspace_id != workspace_id:
                    return jsonify({"status": "error", "message": "Task not found."}), 404
                task.status = "review"
                _safe_db_commit(db)
                event = _safe_create_factory_event(
                    db,
                    workspace_id,
                    "task_marked_review_required",
                    "Task marked review required: {}".format(task.title),
                    task_id=task.id,
                    payload={"reason": reason[:1000]},
                )
                return jsonify(
                    {
                        "status": "success",
                        "task": serialize_task(task),
                        "event": serialize_factory_event(event),
                    }
                )
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/tasks/<int:task_id>/retry-one", methods=["POST"])
        def retry_one_task(task_id):
            payload = request.get_json(silent=True) or {}
            workspace_id = payload.get("workspace_id")
            execution_mode = self.engine.get_execution_mode()
            if execution_mode != "one_task":
                return jsonify(
                    {
                        "status": "error",
                        "message": "Retry One Task requires execution mode one_task.",
                        "execution_mode": execution_mode,
                    }
                ), 403
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403

            db_context = get_db()
            db = next(db_context)
            try:
                workspace = db.get(Workspace, workspace_id)
                if workspace is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400
                task = db.get(Task, task_id)
                if task is None or task.workspace_id != workspace_id:
                    return jsonify({"status": "error", "message": "Task not found."}), 404
                result = _execute_factory_task(db, workspace, task, execution_mode)
                response = {
                    "status": result.get("status"),
                    "task_id": task.id,
                    "task_status": result.get("task_status"),
                    "execution_run_id": result.get("execution_run_id"),
                    "factory_events_created": result.get("factory_events_created", 0),
                    "git": result.get("git", {}),
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "returncode": result.get("returncode"),
                    "timeout_seconds": result.get("timeout_seconds"),
                    "execution_time": result.get("execution_time"),
                    "token_usage": result.get("token_usage", {}),
                    "message": result.get("message", "Retry completed."),
                }
                return jsonify(response), int(result.get("status_code") or 200)
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/work-packets/preview", methods=["POST"])
        def preview_work_packet():
            payload = request.json or {}
            packet_text = payload.get("packet_text")

            if not isinstance(packet_text, str) or not packet_text.strip():
                return jsonify({"status": "error", "message": "packet_text is required."}), 400

            parsed_packet = parse_work_packet(packet_text)
            return jsonify(
                {
                    "status": "success",
                    "packet": parsed_packet,
                    "task_count": len(parsed_packet.get("tasks", [])),
                    "codex_command_count": len(extract_codex_commands(packet_text)),
                }
            )

        @self.app.route("/api/work-packets/stage", methods=["POST"])
        def stage_work_packet():
            payload = request.json or {}
            workspace_id = payload.get("workspace_id")
            packet_text = payload.get("packet_text")

            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            if not isinstance(packet_text, str) or not packet_text.strip():
                return jsonify({"status": "error", "message": "packet_text is required."}), 400

            parsed_packet = parse_work_packet(packet_text)
            parsed_tasks = parsed_packet.get("tasks", [])
            if not parsed_tasks:
                return jsonify({"status": "error", "message": "No codex tasks found in packet."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                if db.get(Workspace, workspace_id) is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400

                work_packet = WorkPacket(
                    workspace_id=workspace_id,
                    title=(parsed_packet.get("title") or "Untitled Work Packet")[:255],
                    risk_level=(parsed_packet.get("risk_level") or "unspecified")[:64],
                    stop_condition=parsed_packet.get("stop_condition") or "",
                    estimated_minutes=(parsed_packet.get("estimated_minutes") or "")[:64],
                    status="staged",
                )
                db.add(work_packet)
                db.flush()

                tasks = [
                    Task(
                        workspace_id=workspace_id,
                        title=(task.get("title") or "Task {}".format(index))[:255],
                        description=task.get("description") or "",
                        status="todo",
                    )
                    for index, task in enumerate(parsed_tasks, start=1)
                ]
                db.add_all(tasks)
                db.flush()
                packet_tasks = [
                    WorkPacketTask(
                        work_packet_id=work_packet.id,
                        task_id=task.id,
                        position=index,
                        status="staged",
                    )
                    for index, task in enumerate(tasks, start=1)
                ]
                db.add_all(packet_tasks)
                db.commit()
                db.refresh(work_packet)
                for task in tasks:
                    db.refresh(task)

                return jsonify(
                    {
                        "status": "success",
                        "work_packet_id": work_packet.id,
                        "packet_title": parsed_packet.get("title"),
                        "created_count": len(tasks),
                        "task_ids": [task.id for task in tasks],
                        "tasks": [serialize_task(task) for task in tasks],
                    }
                )
            except IntegrityError:
                db.rollback()
                return jsonify({"status": "error", "message": "Workspace not found."}), 400
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/work-packets/run", methods=["POST"])
        def run_work_packet():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "JSON object is required."}), 400

            execution_mode = self.engine.get_execution_mode()
            if execution_mode != "one_packet":
                return jsonify(
                    {
                        "status": "error",
                        "message": "Run Packet requires execution mode one_packet.",
                        "execution_mode": execution_mode,
                    }
                ), 403

            workspace_id = payload.get("workspace_id")
            work_packet_id = payload.get("work_packet_id")
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            if not isinstance(work_packet_id, int) or isinstance(work_packet_id, bool):
                return jsonify({"status": "error", "message": "Valid work_packet_id is required."}), 400

            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403

            with self.packet_runner_lock:
                if self.packet_runner_state.get("running"):
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Another packet run is already active.",
                            "runner": dict(self.packet_runner_state),
                        }
                    ), 409
                self.packet_runner_state = {
                    "running": True,
                    "mode": "one_packet",
                    "work_packet_id": work_packet_id,
                    "current_task_id": None,
                    "current_task_title": None,
                    "completed": 0,
                    "total": 0,
                    "message": "Packet runner is loading packet.",
                    "cancel_requested": False,
                }

            db_context = get_db()
            db = next(db_context)
            completed_count = 0
            failed_count = 0
            skipped_count = 0
            execution_run_ids = []
            events_created = 0
            status = "success"
            status_code = 200
            message = "Packet completed successfully."
            try:
                workspace = db.get(Workspace, workspace_id)
                if workspace is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400

                work_packet = db.get(WorkPacket, work_packet_id)
                if work_packet is None or work_packet.workspace_id != workspace_id:
                    return jsonify({"status": "error", "message": "Work packet not found."}), 404

                packet_links = (
                    db.execute(
                        select(WorkPacketTask)
                        .where(WorkPacketTask.work_packet_id == work_packet_id)
                        .order_by(WorkPacketTask.position.asc(), WorkPacketTask.id.asc())
                    )
                    .scalars()
                    .all()
                )
                if not packet_links:
                    return jsonify({"status": "error", "message": "Work packet has no linked tasks."}), 400

                packet_tasks = []
                for link in packet_links:
                    task = db.get(Task, link.task_id)
                    if task is not None and task.workspace_id == workspace_id:
                        packet_tasks.append((link, task))

                if not packet_tasks:
                    return jsonify({"status": "error", "message": "Work packet has no runnable tasks."}), 400

                now = datetime.now(timezone.utc)
                work_packet.status = "running"
                work_packet.started_at = work_packet.started_at or now
                _safe_db_commit(db)

                with self.packet_runner_lock:
                    self.packet_runner_state["total"] = len(packet_tasks)
                    self.packet_runner_state["message"] = "Packet runner started."

                event = _safe_create_factory_event(
                    db,
                    workspace_id,
                    "packet_run_started",
                    "Packet run started: {}".format(work_packet.title),
                    work_packet_id=work_packet_id,
                    payload={"task_count": len(packet_tasks), "execution_mode": execution_mode},
                )
                events_created += 1 if event is not None else 0

                for link, task in packet_tasks:
                    with self.packet_runner_lock:
                        cancel_requested = bool(self.packet_runner_state.get("cancel_requested"))
                    if cancel_requested:
                        link.status = "skipped"
                        skipped_count += 1
                        event = _safe_create_factory_event(
                            db,
                            workspace_id,
                            "packet_task_skipped",
                            "Packet task skipped after cancel request: {}".format(task.title),
                            work_packet_id=work_packet_id,
                            task_id=task.id,
                        )
                        events_created += 1 if event is not None else 0
                        _safe_db_commit(db)
                        continue

                    link.status = "running"
                    link.started_at = datetime.now(timezone.utc)
                    _safe_db_commit(db)
                    with self.packet_runner_lock:
                        self.packet_runner_state["current_task_id"] = task.id
                        self.packet_runner_state["current_task_title"] = task.title
                        self.packet_runner_state["message"] = "Running packet task: {}".format(task.title)

                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_task_started",
                        "Packet task started: {}".format(task.title),
                        work_packet_id=work_packet_id,
                        task_id=task.id,
                    )
                    events_created += 1 if event is not None else 0

                    result = _execute_factory_task(
                        db,
                        workspace,
                        task,
                        execution_mode,
                        work_packet_id=work_packet_id,
                        create_requested_event=False,
                    )
                    if result.get("execution_run_id"):
                        execution_run_ids.append(result.get("execution_run_id"))
                    events_created += int(result.get("factory_events_created") or 0)

                    if result.get("status") == "success":
                        completed_count += 1
                        link.status = "completed"
                        link.completed_at = datetime.now(timezone.utc)
                        event = _safe_create_factory_event(
                            db,
                            workspace_id,
                            "packet_task_completed",
                            "Packet task completed: {}".format(task.title),
                            work_packet_id=work_packet_id,
                            task_id=task.id,
                            execution_run_id=result.get("execution_run_id"),
                            payload={"task_status": getattr(task, "status", None)},
                        )
                        events_created += 1 if event is not None else 0
                        _safe_db_commit(db)
                        with self.packet_runner_lock:
                            self.packet_runner_state["completed"] = completed_count
                        continue

                    failed_count += 1
                    status = "failed"
                    status_code = 500 if result.get("status") != "timeout" else 504
                    message = "Packet stopped after task {} ended with status {}.".format(
                        task.id,
                        result.get("status") or "failed",
                    )
                    link.status = "failed"
                    link.failed_at = datetime.now(timezone.utc)
                    work_packet.status = "failed"
                    work_packet.failed_at = datetime.now(timezone.utc)
                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_task_failed",
                        "Packet task failed: {}".format(task.title),
                        work_packet_id=work_packet_id,
                        task_id=task.id,
                        execution_run_id=result.get("execution_run_id"),
                        payload={"status": result.get("status"), "returncode": result.get("returncode")},
                    )
                    events_created += 1 if event is not None else 0

                    remaining_started = False
                    for remaining_link, remaining_task in packet_tasks:
                        if remaining_started:
                            remaining_link.status = "skipped"
                            skipped_count += 1
                            event = _safe_create_factory_event(
                                db,
                                workspace_id,
                                "packet_task_skipped",
                                "Packet task skipped after failure: {}".format(remaining_task.title),
                                work_packet_id=work_packet_id,
                                task_id=remaining_task.id,
                            )
                            events_created += 1 if event is not None else 0
                        if remaining_link is link:
                            remaining_started = True

                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_run_failed",
                        "Packet run failed: {}".format(work_packet.title),
                        work_packet_id=work_packet_id,
                        payload={
                            "completed_count": completed_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        },
                    )
                    events_created += 1 if event is not None else 0
                    _safe_db_commit(db)
                    break

                if status == "success":
                    work_packet.status = "completed"
                    work_packet.completed_at = datetime.now(timezone.utc)
                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_run_completed",
                        "Packet run completed: {}".format(work_packet.title),
                        work_packet_id=work_packet_id,
                        payload={
                            "completed_count": completed_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        },
                    )
                    events_created += 1 if event is not None else 0
                    _safe_db_commit(db)

                with self.packet_runner_lock:
                    self.packet_runner_state["message"] = message

                return jsonify(
                    {
                        "status": status,
                        "work_packet_id": work_packet_id,
                        "packet_status": work_packet.status,
                        "completed_count": completed_count,
                        "failed_count": failed_count,
                        "skipped_count": skipped_count,
                        "execution_run_ids": execution_run_ids,
                        "events_created": events_created,
                        "message": message,
                    }
                ), status_code
            except Exception:
                db.rollback()
                raise
            finally:
                with self.packet_runner_lock:
                    self.packet_runner_state["running"] = False
                    self.packet_runner_state["current_task_id"] = None
                    self.packet_runner_state["current_task_title"] = None
                    if not self.packet_runner_state.get("message"):
                        self.packet_runner_state["message"] = "Packet runner is idle."
                db_context.close()

        @self.app.route("/api/work-packets/<int:work_packet_id>/continue", methods=["POST"])
        def continue_work_packet(work_packet_id):
            payload = request.get_json(silent=True) or {}
            execution_mode = self.engine.get_execution_mode()
            if execution_mode != "one_packet":
                return jsonify(
                    {
                        "status": "error",
                        "message": "Continue Packet requires execution mode one_packet.",
                        "execution_mode": execution_mode,
                    }
                ), 403

            workspace_id = payload.get("workspace_id")
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403

            with self.packet_runner_lock:
                if self.packet_runner_state.get("running"):
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Another packet run is already active.",
                            "runner": dict(self.packet_runner_state),
                        }
                    ), 409
                self.packet_runner_state = {
                    "running": True,
                    "mode": "one_packet_continue",
                    "work_packet_id": work_packet_id,
                    "current_task_id": None,
                    "current_task_title": None,
                    "completed": 0,
                    "total": 0,
                    "message": "Packet continue is loading packet.",
                    "cancel_requested": False,
                }

            db_context = get_db()
            db = next(db_context)
            completed_count = 0
            failed_count = 0
            skipped_count = 0
            execution_run_ids = []
            events_created = 0
            status = "success"
            status_code = 200
            message = "Packet continue completed successfully."
            try:
                workspace = db.get(Workspace, workspace_id)
                if workspace is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400

                work_packet = db.get(WorkPacket, work_packet_id)
                if work_packet is None or work_packet.workspace_id != workspace_id:
                    return jsonify({"status": "error", "message": "Work packet not found."}), 404

                packet_links = (
                    db.execute(
                        select(WorkPacketTask)
                        .where(WorkPacketTask.work_packet_id == work_packet_id)
                        .order_by(WorkPacketTask.position.asc(), WorkPacketTask.id.asc())
                    )
                    .scalars()
                    .all()
                )
                packet_tasks = []
                for link in packet_links:
                    task = db.get(Task, link.task_id)
                    if task is not None and task.workspace_id == workspace_id:
                        packet_tasks.append((link, task))
                if not packet_tasks:
                    return jsonify({"status": "error", "message": "Work packet has no runnable tasks."}), 400

                unfinished_statuses = {"failed", "skipped", "pending", "todo", "review", "review_required", "staged"}
                run_tasks = [
                    (link, task)
                    for link, task in packet_tasks
                    if (link.status or "").lower() in unfinished_statuses
                    or (task.status or "").lower() in unfinished_statuses
                ]
                if not run_tasks:
                    return jsonify(
                        {
                            "status": "success",
                            "work_packet_id": work_packet_id,
                            "packet_status": work_packet.status,
                            "completed_count": 0,
                            "failed_count": 0,
                            "skipped_count": 0,
                            "execution_run_ids": [],
                            "events_created": 0,
                            "message": "No unfinished packet tasks found.",
                        }
                    )

                work_packet.status = "running"
                work_packet.started_at = work_packet.started_at or datetime.now(timezone.utc)
                _safe_db_commit(db)
                with self.packet_runner_lock:
                    self.packet_runner_state["total"] = len(run_tasks)
                    self.packet_runner_state["message"] = "Continuing packet from first unfinished task."

                event = _safe_create_factory_event(
                    db,
                    workspace_id,
                    "packet_run_continued",
                    "Packet run continued: {}".format(work_packet.title),
                    work_packet_id=work_packet_id,
                    payload={"remaining_task_count": len(run_tasks), "execution_mode": execution_mode},
                )
                events_created += 1 if event is not None else 0

                for link, task in run_tasks:
                    with self.packet_runner_lock:
                        cancel_requested = bool(self.packet_runner_state.get("cancel_requested"))
                    if cancel_requested:
                        link.status = "skipped"
                        skipped_count += 1
                        _safe_db_commit(db)
                        continue

                    link.status = "running"
                    link.started_at = datetime.now(timezone.utc)
                    _safe_db_commit(db)
                    with self.packet_runner_lock:
                        self.packet_runner_state["current_task_id"] = task.id
                        self.packet_runner_state["current_task_title"] = task.title
                        self.packet_runner_state["message"] = "Continuing packet task: {}".format(task.title)

                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_task_started",
                        "Packet task continued: {}".format(task.title),
                        work_packet_id=work_packet_id,
                        task_id=task.id,
                    )
                    events_created += 1 if event is not None else 0

                    result = _execute_factory_task(
                        db,
                        workspace,
                        task,
                        execution_mode,
                        work_packet_id=work_packet_id,
                        create_requested_event=False,
                    )
                    if result.get("execution_run_id"):
                        execution_run_ids.append(result.get("execution_run_id"))
                    events_created += int(result.get("factory_events_created") or 0)

                    if result.get("status") == "success":
                        completed_count += 1
                        link.status = "completed"
                        link.completed_at = datetime.now(timezone.utc)
                        event = _safe_create_factory_event(
                            db,
                            workspace_id,
                            "packet_task_completed",
                            "Packet task completed after continue: {}".format(task.title),
                            work_packet_id=work_packet_id,
                            task_id=task.id,
                            execution_run_id=result.get("execution_run_id"),
                        )
                        events_created += 1 if event is not None else 0
                        _safe_db_commit(db)
                        with self.packet_runner_lock:
                            self.packet_runner_state["completed"] = completed_count
                        continue

                    failed_count += 1
                    status = "failed"
                    status_code = 500 if result.get("status") != "timeout" else 504
                    message = "Packet continue stopped after task {} ended with status {}.".format(
                        task.id,
                        result.get("status") or "failed",
                    )
                    link.status = "failed"
                    link.failed_at = datetime.now(timezone.utc)
                    work_packet.status = "failed"
                    work_packet.failed_at = datetime.now(timezone.utc)
                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_task_failed",
                        "Packet task failed during continue: {}".format(task.title),
                        work_packet_id=work_packet_id,
                        task_id=task.id,
                        execution_run_id=result.get("execution_run_id"),
                    )
                    events_created += 1 if event is not None else 0

                    remaining_started = False
                    for remaining_link, remaining_task in run_tasks:
                        if remaining_started:
                            remaining_link.status = "skipped"
                            skipped_count += 1
                            event = _safe_create_factory_event(
                                db,
                                workspace_id,
                                "packet_task_skipped",
                                "Packet task skipped after continue failure: {}".format(remaining_task.title),
                                work_packet_id=work_packet_id,
                                task_id=remaining_task.id,
                            )
                            events_created += 1 if event is not None else 0
                        if remaining_link is link:
                            remaining_started = True
                    _safe_db_commit(db)
                    break

                if status == "success":
                    all_completed = True
                    for link, task in packet_tasks:
                        if (link.status or "").lower() != "completed":
                            all_completed = False
                            break
                    if all_completed:
                        work_packet.status = "completed"
                        work_packet.completed_at = datetime.now(timezone.utc)
                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_run_completed",
                        "Packet continue completed: {}".format(work_packet.title),
                        work_packet_id=work_packet_id,
                        payload={
                            "completed_count": completed_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        },
                    )
                    events_created += 1 if event is not None else 0
                    _safe_db_commit(db)

                with self.packet_runner_lock:
                    self.packet_runner_state["message"] = message

                return jsonify(
                    {
                        "status": status,
                        "work_packet_id": work_packet_id,
                        "packet_status": work_packet.status,
                        "completed_count": completed_count,
                        "failed_count": failed_count,
                        "skipped_count": skipped_count,
                        "execution_run_ids": execution_run_ids,
                        "events_created": events_created,
                        "message": message,
                    }
                ), status_code
            except Exception:
                db.rollback()
                raise
            finally:
                with self.packet_runner_lock:
                    self.packet_runner_state["running"] = False
                    self.packet_runner_state["current_task_id"] = None
                    self.packet_runner_state["current_task_title"] = None
                db_context.close()

        @self.app.route("/api/work-packets/<int:work_packet_id>/status", methods=["GET"])
        def get_work_packet_status(work_packet_id):
            db_context = get_db()
            db = next(db_context)
            try:
                work_packet = db.get(WorkPacket, work_packet_id)
                if work_packet is None:
                    return jsonify({"status": "error", "message": "Work packet not found."}), 404

                links = (
                    db.execute(
                        select(WorkPacketTask)
                        .where(WorkPacketTask.work_packet_id == work_packet_id)
                        .order_by(WorkPacketTask.position.asc(), WorkPacketTask.id.asc())
                    )
                    .scalars()
                    .all()
                )
                tasks = []
                for link in links:
                    task = db.get(Task, link.task_id)
                    if task is None:
                        continue
                    item = serialize_task(task)
                    item["packet_task_status"] = link.status
                    item["packet_task_position"] = link.position
                    tasks.append(item)

                runs = (
                    db.execute(
                        select(ExecutionRun)
                        .where(ExecutionRun.work_packet_id == work_packet_id)
                        .order_by(ExecutionRun.started_at.desc(), ExecutionRun.id.desc())
                    )
                    .scalars()
                    .all()
                )
                events = (
                    db.execute(
                        select(FactoryEvent)
                        .where(FactoryEvent.work_packet_id == work_packet_id)
                        .order_by(FactoryEvent.created_at.desc(), FactoryEvent.id.desc())
                    )
                    .scalars()
                    .all()
                )
                with self.packet_runner_lock:
                    runner_state = dict(self.packet_runner_state)

                return jsonify(
                    {
                        "status": "success",
                        "work_packet": {
                            "id": work_packet.id,
                            "workspace_id": work_packet.workspace_id,
                            "title": work_packet.title,
                            "risk_level": work_packet.risk_level,
                            "stop_condition": work_packet.stop_condition,
                            "estimated_minutes": work_packet.estimated_minutes,
                            "status": work_packet.status,
                            "created_at": work_packet.created_at.isoformat() if work_packet.created_at else None,
                            "started_at": work_packet.started_at.isoformat() if work_packet.started_at else None,
                            "completed_at": work_packet.completed_at.isoformat() if work_packet.completed_at else None,
                            "failed_at": work_packet.failed_at.isoformat() if work_packet.failed_at else None,
                        },
                        "tasks": tasks,
                        "runs": [serialize_execution_run(run) for run in runs],
                        "events": [serialize_factory_event(event) for event in events],
                        "runner": runner_state,
                    }
                )
            finally:
                db_context.close()

        @self.app.route("/api/work-packets/cancel-run", methods=["POST"])
        def cancel_work_packet_run():
            with self.packet_runner_lock:
                if not self.packet_runner_state.get("running"):
                    return jsonify(
                        {
                            "status": "idle",
                            "message": "No packet run is active.",
                            "runner": dict(self.packet_runner_state),
                        }
                    )
                self.packet_runner_state["cancel_requested"] = True
                self.packet_runner_state["message"] = "Cancel requested; current task will finish first."
                runner_state = dict(self.packet_runner_state)

            workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id is not None:
                db_context = get_db()
                db = next(db_context)
                try:
                    event = _safe_create_factory_event(
                        db,
                        workspace_id,
                        "packet_cancel_requested",
                        "Packet cancel requested.",
                        work_packet_id=runner_state.get("work_packet_id"),
                        task_id=runner_state.get("current_task_id"),
                    )
                    _ = event
                finally:
                    db_context.close()

            return jsonify(
                {
                    "status": "success",
                    "message": "Cancel requested; current task will finish first.",
                    "runner": runner_state,
                }
            )

        @self.app.route("/api/tasks/<int:task_id>", methods=["PUT", "PATCH"])
        def update_task(task_id):
            payload = request.json or {}
            status = payload.get("status")
            allowed_statuses = {"todo", "review", "done"}

            if status not in allowed_statuses:
                return jsonify({"status": "error", "message": "Invalid status."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                task = db.get(Task, task_id)
                if task is None:
                    return jsonify({"status": "error", "message": "Task not found."}), 404

                task.status = status
                db.commit()
                db.refresh(task)
                return jsonify(serialize_task(task))
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
        def delete_task(task_id):
            db_context = get_db()
            db = next(db_context)
            try:
                task = db.get(Task, task_id)
                if task is None:
                    return jsonify({"status": "error", "message": "Task not found."}), 404

                db.delete(task)
                db.commit()
                return jsonify({"status": "success", "message": "Task deleted.", "id": task_id})
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/tasks/run-one", methods=["POST"])
        def run_one_task():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "JSON object is required."}), 400

            execution_mode = self.engine.get_execution_mode()
            if execution_mode != "one_task":
                return jsonify(
                    {
                        "status": "error",
                        "message": "Run One requires execution mode one_task.",
                        "execution_mode": execution_mode,
                    }
                ), 403

            workspace_id = payload.get("workspace_id")
            task_id = payload.get("task_id")
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            if not isinstance(task_id, int) or isinstance(task_id, bool):
                return jsonify({"status": "error", "message": "Valid task_id is required."}), 400

            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403

            db_context = get_db()
            db = next(db_context)
            try:
                workspace = db.get(Workspace, workspace_id)
                if workspace is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400

                task = db.get(Task, task_id)
                if task is None or task.workspace_id != workspace_id:
                    return jsonify({"status": "error", "message": "Task not found."}), 404

                result = _execute_factory_task(
                    db,
                    workspace,
                    task,
                    execution_mode,
                    create_requested_event=True,
                )
                status_code = result.pop("status_code", 200)
                return jsonify(result), status_code
            finally:
                db_context.close()

        @self.app.route("/api/tasks/auto-run", methods=["POST"])
        def auto_run_tasks():
            payload = request.json or {}
            workspace_id = payload.get("workspace_id")
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403
            execution_mode = self.engine.get_execution_mode()
            if execution_mode != "autopilot":
                return jsonify(
                    {
                        "status": "error",
                        "message": "Auto-Pilot is disabled while execution mode is manual.",
                        "execution_mode": execution_mode,
                        "queue": self.autonomous_queue.status(),
                    }
                ), 403
            if not self.autonomous_queue.is_configured():
                return jsonify(
                    {
                        "status": "error",
                        "message": "DISCORD_WEBHOOK_URL must be configured before enabling Auto-Pilot.",
                    }
                ), 503

            started, queue_status = self.autonomous_queue.start(
                workspace_id,
                os.path.abspath(self.engine.target_dir),
            )
            if not started:
                return jsonify(
                    {"status": "error", "message": "Auto-Pilot is already running.", "queue": queue_status}
                ), 409
            return jsonify({"status": "success", "queue": queue_status}), 202

        @self.app.route("/api/tasks/auto-run/status", methods=["GET"])
        def auto_run_status():
            return jsonify({"status": "success", "queue": self.autonomous_queue.status()})

        @self.app.route("/api/execution-mode", methods=["GET"])
        def get_execution_mode():
            current_mode = self.engine.get_execution_mode()
            return jsonify(
                {
                    "status": "success",
                    "execution_mode": current_mode,
                    "allowed_modes": ["manual", "one_task", "one_packet", "autopilot"],
                    "autopilot_allowed": current_mode == "autopilot",
                    "automatic_analysis_enabled": self.engine.is_automatic_analysis_enabled(),
                }
            )

        @self.app.route("/api/execution-mode", methods=["POST"])
        def set_execution_mode():
            payload = request.json or {}
            current_mode = self.engine.set_execution_mode(payload.get("execution_mode"))
            return jsonify(
                {
                    "status": "success",
                    "execution_mode": current_mode,
                    "allowed_modes": ["manual", "one_task", "one_packet", "autopilot"],
                    "autopilot_allowed": current_mode == "autopilot",
                    "automatic_analysis_enabled": self.engine.is_automatic_analysis_enabled(),
                }
            )

        @self.app.route("/api/footprint", methods=["POST"])
        def create_footprint():
            payload = request.json or {}
            workspace_id = payload.get("workspace_id")
            persona = payload.get("persona")
            action_type = payload.get("action_type")
            content = payload.get("content")

            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400
            if not isinstance(persona, str) or not persona.strip():
                return jsonify({"status": "error", "message": "Persona is required."}), 400
            if not isinstance(action_type, str) or not action_type.strip():
                return jsonify({"status": "error", "message": "Action type is required."}), 400
            if not isinstance(content, str) or not content.strip():
                return jsonify({"status": "error", "message": "Content is required."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                if db.get(Workspace, workspace_id) is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400

                footprint = Footprint(
                    workspace_id=workspace_id,
                    persona=persona.strip(),
                    action_type=action_type.strip(),
                    content=content,
                )
                db.add(footprint)
                db.commit()
                db.refresh(footprint)
                return jsonify(serialize_footprint(footprint)), 201
            except IntegrityError:
                db.rollback()
                return jsonify({"status": "error", "message": "Workspace not found."}), 400
            except Exception:
                db.rollback()
                raise
            finally:
                db_context.close()

        @self.app.route("/api/history", methods=["GET"])
        def get_project_history():
            workspace_id = request.args.get("workspace_id", type=int)
            if workspace_id is None:
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                footprints = db.execute(
                    select(Footprint)
                    .where(Footprint.workspace_id == workspace_id)
                    .order_by(Footprint.created_at.desc(), Footprint.id.desc())
                ).scalars().all()
                return jsonify([serialize_footprint(footprint) for footprint in footprints])
            finally:
                db_context.close()

        @self.app.route("/api/run-profiler", methods=["POST"])
        def run_profiler():
            payload = request.json or {}
            workspace_id = payload.get("workspace_id")
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            result = self.engine.profile_user_habits(workspace_id)
            status_code = 200 if result.get("status") == "success" else 500
            return jsonify(result), status_code

        @self.app.route("/api/execute-codex", methods=["POST"])
        def execute_codex():
            payload = request.json or {}
            prompt = payload.get("prompt")
            workspace_id = payload.get("workspace_id")

            if not isinstance(prompt, str) or not prompt.strip():
                return jsonify({"status": "error", "message": "Prompt is required."}), 400
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                workspace = db.get(Workspace, workspace_id)
                if workspace is None:
                    return jsonify({"status": "error", "message": "Workspace not found."}), 400
                workspace_path = os.path.abspath(workspace.local_path)
            finally:
                db_context.close()

            if not os.path.isdir(workspace_path):
                return jsonify({"status": "error", "message": "Workspace directory not found."}), 400

            command_prompt = prompt.strip()
            try:
                codex_result = CodexRunner(timeout_factory=calculate_prompt_timeout).run(
                    command_prompt,
                    workspace_path,
                )
            except OSError as exception:
                return jsonify(
                    {
                        "status": "error",
                        "stdout": "",
                        "stderr": str(exception),
                        "returncode": -1,
                        "timeout_seconds": 0,
                        "execution_time": 0,
                        "token_usage": {},
                    }
                ), 500

            try:
                footprint = save_footprints(
                    [
                        Footprint(
                            workspace_id=workspace_id,
                            persona="cto",
                            action_type="codex_execution",
                            content=command_prompt,
                        )
                    ]
                )[0]
            except Exception:
                raise

            status_code = 200
            if codex_result.status == "failed":
                status_code = 500
            elif codex_result.status == "timeout":
                status_code = 504

            return jsonify(
                {
                    "status": codex_result.status,
                    "stdout": codex_result.stdout,
                    "stderr": codex_result.stderr,
                    "returncode": codex_result.returncode,
                    "timeout_seconds": codex_result.timeout_seconds,
                    "execution_time": codex_result.execution_time,
                    "token_usage": codex_result.token_usage,
                    "footprint_id": footprint.id,
                }
            ), status_code

        @self.app.route("/api/chat-history", methods=["GET"])
        def get_chat_history():
            workspace_id = request.args.get("workspace_id", type=int)
            if workspace_id is None:
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            db_context = get_db()
            db = next(db_context)
            try:
                messages = db.execute(
                    select(Message)
                    .join(ChatSession, Message.session_id == ChatSession.id)
                    .where(
                        ChatSession.workspace_id == workspace_id,
                        ChatSession.active_persona == "cto",
                    )
                    .order_by(Message.created_at.asc(), Message.id.asc())
                ).scalars().all()
                return jsonify([serialize_message(message) for message in messages])
            finally:
                db_context.close()

        @self.app.route("/api/architecture", methods=["GET"])
        def get_architecture():
            architecture_path = os.path.abspath(
                os.path.join(self.engine.target_dir, ".nexus", "architecture.mmd")
            )
            try:
                with open(architecture_path, "r", encoding="utf-8") as file:
                    return jsonify({"status": "success", "data": file.read()})
            except FileNotFoundError:
                return jsonify(
                    {
                        "status": "empty",
                        "data": "",
                        "message": "No architecture canvas has been generated for this workspace.",
                    }
                )
            except OSError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 500

        @self.app.route("/api/project-brain", methods=["GET"])
        def get_project_brain():
            brain_path = os.path.abspath(
                os.path.join(self.engine.target_dir, ".nexus", "brain.md")
            )
            try:
                with open(brain_path, "r", encoding="utf-8") as file:
                    return jsonify({"status": "success", "data": file.read()})
            except FileNotFoundError:
                return jsonify(
                    {
                        "status": "empty",
                        "data": "",
                        "message": "No project brain has been generated for this workspace.",
                    }
                )
            except OSError as exception:
                return jsonify({"status": "error", "message": str(exception)}), 500

        @self.app.route("/api/agents", methods=["GET"])
        def get_agents():
            db_context = get_db()
            db = next(db_context)
            try:
                profiles = db.execute(
                    select(UserProfile).order_by(UserProfile.preference_key.asc())
                ).scalars().all()
                habits = [
                    {
                        "key": profile.preference_key,
                        "value": profile.preference_value,
                    }
                    for profile in profiles
                ]
            finally:
                db_context.close()

            try:
                resolved = self.engine.resolve_agent_model("cto", fallback_profile="deep")
                active_model = resolved.get("model") or "Auto-select at runtime"
                provider = resolved.get("provider") or "auto"
            except Exception:
                active_model = "Auto-select at runtime"
                provider = self.engine.settings.get("provider", "auto")

            model_config = {"provider": provider, "model": active_model}
            return jsonify(
                {
                    "agents": [
                        {
                            "id": "cto",
                            "name": "CTO Copilot",
                            "title": "Orchestrator",
                            "system_prompt": prompts.CTO_ORCHESTRATOR_PROMPT,
                            "active_model": model_config,
                            "habits": habits,
                        },
                        {
                            "id": "architect",
                            "name": "Architect",
                            "title": "System Design",
                            "system_prompt": prompts.load_persona("architect")
                            or "Architect system prompt is not configured.",
                            "active_model": model_config,
                            "habits": [],
                        },
                        {
                            "id": "tech_lead",
                            "name": "Tech Lead",
                            "title": "Execution",
                            "system_prompt": prompts.load_persona("tech_lead")
                            or "Tech Lead system prompt is not configured.",
                            "active_model": model_config,
                            "habits": [],
                        },
                    ]
                }
            )

        @self.app.route("/api/settings", methods=["GET"])
        def get_settings():
            return jsonify(self.engine.public_settings())

        @self.app.route("/api/settings", methods=["POST"])
        def save_settings():
            data = request.json or {}
            result = self.engine.save_settings(data)
            return jsonify(result)

        @self.app.route("/api/models", methods=["GET"])
        def list_models():
            provider = request.args.get("provider")
            force = request.args.get("force", "false").lower() == "true"
            result = self.engine.list_models(provider=provider, force=force)
            return jsonify(result)

        @self.app.route("/api/models/curated", methods=["GET"])
        def list_curated_models():
            provider = request.args.get("provider")
            result = self.engine.list_curated_models(provider=provider)
            return jsonify(result)

        @self.app.route("/api/bundle-self", methods=["POST"])
        def bundle_nexus():
            out_file = self.engine.bundle_self()
            return jsonify({"status": "success", "file": out_file})

        @self.app.route("/api/bundle", methods=["POST"])
        def bundle_selected():
            payload = request.json or {}
            paths = payload.get("paths", [])

            if not paths:
                return jsonify({"status": "error", "message": "No selection"}), 400

            out_file = self.engine.bundle_focused(paths)
            return jsonify({"status": "success", "file": out_file})

        @self.app.route("/api/bundle-all", methods=["POST"])
        def bundle_all():
            result = self.engine.build_full_minified_bundle()
            return jsonify(result)

        @self.app.route("/api/chat-bundle", methods=["POST"])
        def build_chat_bundle():
            payload = request.json or {}
            message = (payload.get("message") or "").strip()
            selected_paths = payload.get("selected_paths", [])
            mode = (payload.get("mode") or "task").strip()

            result = self.engine.build_chat_bundle(
                message=message,
                selected_paths=selected_paths,
                mode=mode,
            )
            return jsonify(result)

        @self.app.route("/api/context", methods=["GET"])
        def get_context():
            path = request.args.get("path")
            content = self.engine.read_context(path)

            if content:
                return jsonify({"status": "success", "data": content})

            return jsonify({"status": "empty", "data": None})

        @self.app.route("/api/context", methods=["POST"])
        def build_context():
            payload = request.json or {}
            path = payload.get("path")
            result = self.engine.build_ai_context(path)
            return jsonify(result)

        @self.app.route("/api/generate-gem-context", methods=["POST"])
        def generate_gem_context():
            result = self.engine.generate_gem_context()
            return jsonify(result)

        @self.app.route("/api/ai-tool", methods=["POST"])
        def run_ai_tool():
            payload = request.json or {}
            tool_type = payload.get("type")
            result = self.engine.run_ai_tool(tool_type)
            return jsonify(result)

        @self.app.route("/api/chat", methods=["POST"])
        def chat():
            payload = request.json or {}

            message = (payload.get("message") or "").strip()
            selected_paths = payload.get("selected_paths", [])
            requested_persona = payload.get("persona") or "cto"

            if not message:
                return jsonify({"status": "error", "message": "Message is required."}), 400
            if not isinstance(requested_persona, str):
                return jsonify({"status": "error", "message": "Invalid persona."}), 400

            persona = requested_persona.strip().lower()
            if persona not in prompts.PERSONA_MODES:
                return jsonify({"status": "error", "message": "Invalid persona."}), 400

            workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id is None:
                return jsonify({"status": "error", "message": "Select an active workspace before chatting."}), 400

            session_id = bind_cto_chat_session(workspace_id)
            known_preferences = get_known_user_preferences()
            workspace_path = os.path.abspath(self.engine.target_dir)

            def generate_events():
                # Commit the complete memory exchange before emitting any SSE frame.
                response_chunks = []
                events = []
                chunks = self.engine.chat_stream(
                    session_id=session_id,
                    message=message,
                    selected_paths=selected_paths,
                    mode=persona,
                    known_preferences=known_preferences,
                )
                for chunk in chunks:
                    response_chunks.append(chunk)
                    events.append(f"data: {json.dumps({'chunk': chunk})}\n\n")

                response_text = "".join(response_chunks)
                if persona == "architect":
                    persist_architect_diagram(workspace_path, response_text)
                elif persona == "tech_lead":
                    save_tech_lead_tasks(workspace_id, response_text)

                save_footprints(
                    [
                        Footprint(
                            workspace_id=workspace_id,
                            persona=persona,
                            action_type="chat_prompt",
                            content=message,
                        ),
                        Footprint(
                            workspace_id=workspace_id,
                            persona=persona,
                            action_type="chat_response",
                            content=response_text,
                        ),
                    ]
                )

                for event in events:
                    yield event

            return Response(
                stream_with_context(generate_events()),
                content_type="text/event-stream",
            )

    def run(self, port=5000):
        print(f"[*] NEXUS DASHBOARD ACTIVE: http://0.0.0.0:{port}", flush=True)
        self.app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)


def main():
    import argparse

    from engine import NexusEngine

    parser = argparse.ArgumentParser(description="Nexus dashboard")
    parser.add_argument("--dir", default="..")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    engine = NexusEngine(os.path.abspath(args.dir))
    engine.run_analysis()
    NexusDashboard(engine).run(port=args.port)


if __name__ == "__main__":
    main()
