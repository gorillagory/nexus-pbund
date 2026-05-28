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
from models import ChatSession, Footprint, Message, Task, UserProfile, Workspace
from src.api.project_routes import projects_blueprint


active_watcher = None
active_watcher_lock = Lock()
telemetry_lock = Lock()


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
        command = ["codex", "exec", prompt]
        timeout_seconds = calculate_prompt_timeout(prompt)
        environment = os.environ.copy()
        environment.update(
            {
                "CI": "true",
                "DEBIAN_FRONTEND": "noninteractive",
                "PYTHONUNBUFFERED": "1",
            }
        )
        start_time = time.monotonic()
        try:
            process = subprocess.run(
                command,
                cwd=workspace_path,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exception:
            stdout = (
                exception.stdout.decode("utf-8", errors="replace")
                if isinstance(exception.stdout, bytes)
                else (exception.stdout or "")
            )
            stderr = (
                exception.stderr.decode("utf-8", errors="replace")
                if isinstance(exception.stderr, bytes)
                else (exception.stderr or "")
            )
            error = f"Codex execution timed out after {timeout_seconds} seconds."
            append_codex_telemetry(
                {
                    "task_id": task.get("id"),
                    "action": "codex_exec",
                    "execution_time": round(time.monotonic() - start_time, 3),
                    "return_code": -1,
                    "timeout_seconds": timeout_seconds,
                    "token_usage": _extract_cli_token_usage(f"{stdout}\n{stderr}"),
                    "stderr": stderr,
                    "error": error,
                },
                base_dir=workspace_path,
            )
            cls._write_crash_log(
                workspace_path,
                exception,
                stdout=exception.stdout,
                stderr=exception.stderr,
            )
            raise RuntimeError(error) from exception

        append_codex_telemetry(
            {
                "task_id": task.get("id"),
                "action": "codex_exec",
                "execution_time": round(time.monotonic() - start_time, 3),
                "return_code": process.returncode,
                "timeout_seconds": timeout_seconds,
                "token_usage": _extract_cli_token_usage(f"{process.stdout}\n{process.stderr}"),
                "stderr": process.stderr,
                "error": process.stderr if process.returncode != 0 else "",
            },
            base_dir=workspace_path,
        )

        if process.returncode != 0:
            error = process.stderr.strip() or process.stdout.strip() or "Codex execution failed."
            exception = RuntimeError(error)
            cls._write_crash_log(
                workspace_path,
                exception,
                stdout=process.stdout,
                stderr=process.stderr,
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

        @self.app.route("/api/tasks/auto-run", methods=["POST"])
        def auto_run_tasks():
            payload = request.json or {}
            workspace_id = payload.get("workspace_id")
            if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
                return jsonify({"status": "error", "message": "Valid workspace_id is required."}), 400

            active_workspace_id = get_workspace_id(self.engine.target_dir)
            if workspace_id != active_workspace_id:
                return jsonify({"status": "error", "message": "Workspace is not active."}), 403
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
                process = subprocess.Popen(
                    ["codex", "exec", command_prompt],
                    cwd=workspace_path,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, stderr = process.communicate()
            except OSError as exception:
                return jsonify({"status": "error", "stdout": "", "stderr": str(exception)}), 500

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

            execution_status = (
                "success"
                if process.returncode == 0 and not stderr.strip()
                else "error"
            )
            return jsonify(
                {
                    "status": execution_status,
                    "stdout": stdout,
                    "stderr": stderr,
                    "footprint_id": footprint.id,
                }
            ), (200 if execution_status == "success" else 500)

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
            return jsonify(self.engine.settings)

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
