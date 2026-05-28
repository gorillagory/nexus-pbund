import asyncio
import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from sqlalchemy import select

import prompts
from ai_clients.factory import AIClientFactory
from bundle_builders.chat_bundle_builder import ChatBundleBuilder
from chat_session_store import ChatSessionStore
from database import get_db
from model_registry import ModelRegistry
from models import Footprint, Task, UserProfile, Workspace
from task_router import TaskRouter
from threading import Lock, Timer
from watchdog.events import FileSystemEventHandler


load_dotenv()

LOGGER = logging.getLogger(__name__)

ALLOWED_EXECUTION_MODES = {"manual", "autopilot"}


EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "pbund",
    "__pycache__",
    ".venv",
    "storage",
    "bootstrap/cache",
    "public/build",
    ".idea",
    ".vscode",
    "tests",
}

HARD_IGNORE_DIR_NAMES = {
    ".git",
    ".nexus",
    ".codex",
    "output",
    "context",
    "pbund",
    "nexus-pbund",
    "bundle_builders",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "env",
    ".env",
    "site-packages",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".postgres-data",
    ".postgress-data",
    "postgres-data",
    "postgres_data",
    "pgdata",
    "storage",
    "logs",
    "tmp",
    "temp",
    "cache",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
}

EXCLUDE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".pdf",
    ".zip",
    ".pyc",
    ".log",
    ".sqlite",
    ".lock",
}

ROLE_MAP = [
    ("controller", r"app/Http/Controllers"),
    ("model", r"app/Models"),
    ("service", r"app/Services"),
    ("middleware", r"app/Http/Middleware"),
    ("request", r"app/Http/Requests"),
    ("provider", r"app/Providers"),
    ("blade", r"\.blade\.php$"),
    ("vue", r"\.vue$"),
    ("route", r"routes/"),
    ("migration", r"database/migrations"),
]

GLOBAL_PORTFOLIO_PATH = "/home/dev/garage/agentic-mesh/.global_portfolio.md"
PROJECT_ROOTS = (
    "/home/dev/garage/workspaces",
    "/home/dev/garage/imported",
)
CARTOGRAPHER_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "vendor",
    "venv",
}
CARTOGRAPHER_PROMPT = (
    "You are a Cartographer. Analyze this directory tree and summarize the "
    "project stack, core architecture, and primary purpose in a concise "
    "markdown document."
)
IGNORE_PATTERNS = [
    ".git",
    "node_modules",
    "vendor",
    "__pycache__",
    ".env",
    ".log",
    ".tmp",
    "scratch",
]
WATCHDOG_DEBOUNCE_SECONDS = 5.0


def calculate_prompt_timeout(prompt):
    prompt_length = len(prompt or "")
    return min(300, 45 + ((prompt_length + 49) // 50))


def extract_json_int_array(text):
    if not text:
        return []

    cleaned = str(text).strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:-1]).strip()

    start = cleaned.find("[")
    if start == -1:
        return []

    depth = 0
    end = -1
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break

    if end == -1:
        return []

    try:
        parsed = json.loads(cleaned[start:end])
    except (TypeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    return [
        item
        for item in parsed
        if isinstance(item, int) and not isinstance(item, bool)
    ]


def should_ignore_workspace_path(file_path, workspace_root):
    try:
        absolute_path = os.path.abspath(file_path)
        absolute_root = os.path.abspath(workspace_root)
        if os.path.commonpath([absolute_root, absolute_path]) != absolute_root:
            return True
    except (TypeError, ValueError):
        return True

    relative_path = os.path.relpath(absolute_path, absolute_root)
    components = relative_path.split(os.sep)
    if any(component in HARD_IGNORE_DIR_NAMES for component in components):
        return True

    return absolute_path.endswith(tuple(EXCLUDE_EXTS))


def normalize_execution_mode(value):
    if value is None:
        return "manual"

    mode = str(value).strip().lower()
    if mode in ALLOWED_EXECUTION_MODES:
        return mode
    return "manual"


class NexusEngine:
    def __init__(self, target_dir):
        self.target_dir = os.path.abspath(target_dir)
        self.pbund_dir = os.path.dirname(os.path.abspath(__file__))
        self.out_dir = os.path.join(self.pbund_dir, "output")
        self.context_dir = os.path.join(self.pbund_dir, "context")
        self.settings_file = os.path.join(self.pbund_dir, "settings.json")

        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.context_dir, exist_ok=True)

        self.state = self._empty_state()

        self.settings = self.load_settings()
        self.chat_store = ChatSessionStore(max_messages=20)
        self.chat_bundle_builder = ChatBundleBuilder(
            target_dir=self.target_dir,
            output_dir=self.out_dir,
            context_dir=self.context_dir,
        )
        self.model_registry = ModelRegistry(self.settings)
        self._brain_lock = Lock()
        self.telemetry_logger = None

    def _log_telemetry(self, event):
        if not self.telemetry_logger:
            return

        try:
            self.telemetry_logger(event, base_dir=self.target_dir)
        except Exception:
            LOGGER.exception("Telemetry logging failed.")

    @staticmethod
    def _extract_token_usage(raw):
        if not isinstance(raw, dict):
            return None

        usage = raw.get("usage") or raw.get("usageMetadata")
        return usage if isinstance(usage, dict) else None

    @staticmethod
    def _empty_state():
        return {
            "files": {},
            "relations": {},
            "routes": [],
            "recent_changes": [],
            "last_update": "Never",
        }

    def change_target(self, new_dir):
        if not isinstance(new_dir, str) or not new_dir.strip():
            raise ValueError("Project path is required.")

        target_dir = os.path.abspath(os.path.expanduser(new_dir.strip()))
        if not os.path.isdir(target_dir):
            raise ValueError(f"Project directory not found: {target_dir}")

        self.target_dir = target_dir
        self.state = self._empty_state()
        self.chat_bundle_builder = ChatBundleBuilder(
            target_dir=self.target_dir,
            output_dir=self.out_dir,
            context_dir=self.context_dir,
        )
        self.run_analysis()

        return {"status": "success", "target_dir": self.target_dir}

    def get_global_portfolio(self):
        try:
            with open(GLOBAL_PORTFOLIO_PATH, "r", encoding="utf-8") as file:
                content = file.read()
        except OSError:
            return []

        projects = []
        headings = list(re.finditer(r"^##\s+(.+?)\s*$", content, re.MULTILINE))

        for index, heading in enumerate(headings):
            name = heading.group(1).strip()
            section_end = (
                headings[index + 1].start()
                if index + 1 < len(headings)
                else len(content)
            )
            section = content[heading.end():section_end]
            recorded_path = re.search(r"`((?:workspaces|imported)/[^`]+)`", section)

            candidates = []
            if recorded_path:
                candidates.append(os.path.join("/home/dev/garage", recorded_path.group(1)))
            candidates.extend(os.path.join(root, name) for root in PROJECT_ROOTS)

            project_path = next(
                (os.path.abspath(path) for path in candidates if os.path.isdir(path)),
                os.path.abspath(candidates[0]),
            )
            projects.append({"name": name, "path": project_path})

        return projects

    def load_settings(self):
        defaults = {
            "provider": "auto",
            "gemini_api_key": "",
            "gemini_model": "",
            "openai_api_key": "",
            "openai_model": "",
            "model_selection_mode": "auto",
            "execution_mode": "manual",
        }

        saved = {}
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as file:
                    saved = json.load(file)
            except Exception:
                saved = {}

        legacy_api_key = (saved.get("api_key") or "").strip()
        legacy_provider = (saved.get("provider") or "").strip().lower()

        defaults.update(saved)

        if legacy_api_key and not defaults.get("gemini_api_key"):
            defaults["gemini_api_key"] = legacy_api_key

        if legacy_provider in {"gemini", "openai", "auto"}:
            defaults["provider"] = legacy_provider

        gemini_env_key = os.getenv("GEMINI_API_KEY")
        if gemini_env_key is not None:
            defaults["gemini_api_key"] = gemini_env_key.strip()

        openai_env_key = os.getenv("OPENAI_API_KEY")
        if openai_env_key is not None:
            defaults["openai_api_key"] = openai_env_key.strip()

        if defaults["model_selection_mode"] not in {"auto", "manual"}:
            defaults["model_selection_mode"] = "auto"

        defaults["execution_mode"] = normalize_execution_mode(defaults.get("execution_mode"))

        return defaults

    def save_settings(self, new_settings):
        allowed_keys = {
            "provider",
            "api_key",
            "gemini_api_key",
            "gemini_model",
            "openai_api_key",
            "openai_model",
            "model_selection_mode",
            "execution_mode",
        }
        secret_keys = {"api_key", "gemini_api_key", "openai_api_key"}

        for key, value in new_settings.items():
            if key in allowed_keys:
                submitted_value = "" if value is None else str(value).strip()
                if key in secret_keys and not submitted_value and self.settings.get(key):
                    continue
                self.settings[key] = value

        provider = (self.settings.get("provider") or "auto").strip().lower()
        if provider not in {"auto", "gemini", "openai"}:
            self.settings["provider"] = "auto"

        mode = (self.settings.get("model_selection_mode") or "auto").strip().lower()
        if mode not in {"auto", "manual"}:
            self.settings["model_selection_mode"] = "auto"

        self.settings["execution_mode"] = normalize_execution_mode(self.settings.get("execution_mode"))

        with open(self.settings_file, "w", encoding="utf-8") as file:
            json.dump(self.settings, file, indent=2)

        self.model_registry = ModelRegistry(self.settings)

        return {"status": "success", "settings": self.public_settings()}

    def get_execution_mode(self):
        return normalize_execution_mode(self.settings.get("execution_mode"))

    def set_execution_mode(self, mode):
        normalized_mode = normalize_execution_mode(mode)
        self.save_settings({"execution_mode": normalized_mode})
        return normalized_mode

    def public_settings(self):
        public = dict(self.settings)
        public.pop("gemini_api_key", None)
        public.pop("openai_api_key", None)
        public.pop("api_key", None)
        public["execution_mode"] = self.get_execution_mode()

        gemini_key = (self.settings.get("gemini_api_key") or "").strip()
        openai_key = (self.settings.get("openai_api_key") or "").strip()
        gemini_env_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        openai_env_key = (os.getenv("OPENAI_API_KEY") or "").strip()

        public["gemini_api_key_configured"] = bool(gemini_key or gemini_env_key)
        public["openai_api_key_configured"] = bool(openai_key or openai_env_key)
        return public

    def list_models(self, provider=None, force=False):
        start_time = time.monotonic()
        result = self.model_registry.refresh(provider=provider, force=force)
        if provider:
            status = result.get("status") if isinstance(result, dict) else None
            error = result.get("message", "") if status == "error" else ""
        else:
            provider_results = result.values() if isinstance(result, dict) else []
            failures = [
                item.get("message", "Model listing failed.")
                for item in provider_results
                if isinstance(item, dict) and item.get("status") == "error"
            ]
            status = "error" if failures else "success"
            error = "\n".join(failures)
        self._log_telemetry(
            {
                "action": "ai_list_models",
                "provider": provider or "all",
                "execution_time": round(time.monotonic() - start_time, 3),
                "return_code": 0 if status == "success" else 1,
                "token_usage": None,
                "stderr": error,
                "error": error,
            }
        )
        return result

    def list_curated_models(self, provider=None):
        start_time = time.monotonic()
        result = self.model_registry.get_curated_catalog(provider=provider)
        status = result.get("status") if isinstance(result, dict) else None
        error = result.get("message", "") if status == "error" else ""
        self._log_telemetry(
            {
                "action": "ai_list_curated_models",
                "provider": provider or "all",
                "execution_time": round(time.monotonic() - start_time, 3),
                "return_code": 0 if status == "success" else 1,
                "token_usage": None,
                "stderr": error,
                "error": error,
            }
        )
        return result

    def resolve_model(
        self,
        task_profile="balanced",
        provider_override=None,
        allow_manual_override=True,
    ):
        selection_mode = (self.settings.get("model_selection_mode") or "auto").strip().lower()

        manual_overrides = {}
        if selection_mode == "manual" and allow_manual_override:
            manual_overrides = {
                "gemini": (self.settings.get("gemini_model") or "").strip(),
                "openai": (self.settings.get("openai_model") or "").strip(),
            }

        provider_preference = provider_override or self.settings.get("provider") or "auto"

        return self.model_registry.choose(
            task_profile=task_profile,
            provider_preference=provider_preference,
            manual_overrides=manual_overrides,
            use_configured_fallback=allow_manual_override,
        )

    def resolve_agent_model(self, agent_role, fallback_profile="balanced"):
        route = TaskRouter.resolve_agent_route(agent_role)
        if route is None:
            return self.resolve_model(task_profile=fallback_profile)

        configured_provider = (self.settings.get("provider") or "auto").strip().lower()
        if configured_provider in {"gemini", "openai"}:
            provider_override = configured_provider
        else:
            provider_override = next(
                (
                    provider
                    for provider in route["provider_order"]
                    if (self.settings.get(f"{provider}_api_key") or "").strip()
                ),
                route["provider_order"][0],
            )

        return self.resolve_model(
            task_profile=route["task_profile"],
            provider_override=provider_override,
            allow_manual_override=False,
        )

    def _build_client(self, provider):
        return AIClientFactory.build(provider, self.settings)

    def _call_ai(
        self,
        prompt,
        task_profile="balanced",
        provider_override=None,
        out_filename=None,
        is_context=False,
        rel_path=None,
        agent_role=None,
    ):
        start_time = time.monotonic()
        provider = None
        model = None
        timeout_seconds = calculate_prompt_timeout(prompt)
        try:
            route = TaskRouter.resolve_agent_route(agent_role)
            active_profile = route["task_profile"] if route else task_profile
            if route and provider_override is None:
                resolved = self.resolve_agent_model(agent_role, fallback_profile=task_profile)
            else:
                resolved = self.resolve_model(
                    task_profile=active_profile,
                    provider_override=provider_override,
                    allow_manual_override=route is None,
                )

            provider = resolved["provider"]
            model = resolved["model"]

            client = self._build_client(provider)
            result = client.generate(prompt, model=model, timeout=timeout_seconds)
            self._log_telemetry(
                {
                    "action": "ai_generate",
                    "provider": provider,
                    "model": result.get("model", model),
                    "execution_time": round(time.monotonic() - start_time, 3),
                    "return_code": 0,
                    "timeout_seconds": timeout_seconds,
                    "token_usage": self._extract_token_usage(result.get("raw")),
                    "stderr": "",
                    "error": "",
                }
            )

            text = result["text"]
            raw = result["raw"]

            if is_context and rel_path:
                json_path = self.get_context_path(rel_path).replace(".md", ".json")
                with open(json_path, "w", encoding="utf-8") as file:
                    json.dump(raw, file, indent=2)

                with open(self.get_context_path(rel_path), "w", encoding="utf-8") as file:
                    file.write(text)

                return {
                    "status": "success",
                    "data": text,
                    "provider": provider,
                    "model": result["model"],
                    "task_profile": active_profile,
                    "selection_mode": resolved.get("selection_mode"),
                }

            if out_filename:
                out_path = os.path.join(self.out_dir, out_filename)
                with open(out_path, "w", encoding="utf-8") as file:
                    file.write(text)

                return {
                    "status": "success",
                    "data": text,
                    "file": f"output/{out_filename}",
                    "provider": provider,
                    "model": result["model"],
                    "task_profile": active_profile,
                    "selection_mode": resolved.get("selection_mode"),
                }

            return {
                "status": "success",
                "data": text,
                "provider": provider,
                "model": result["model"],
                "task_profile": active_profile,
                "selection_mode": resolved.get("selection_mode"),
            }
        except Exception as exception:
            self._log_telemetry(
                {
                    "action": "ai_generate",
                    "provider": provider,
                    "model": model,
                    "execution_time": round(time.monotonic() - start_time, 3),
                    "return_code": 1,
                    "timeout_seconds": timeout_seconds,
                    "token_usage": None,
                    "stderr": str(exception),
                    "error": str(exception),
                }
            )
            return {
                "status": "error",
                "message": str(exception),
            }

    def _build_workspace_tree(self, workspace_path):
        lines = [f"{os.path.basename(os.path.normpath(workspace_path))}/"]

        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = sorted(
                directory
                for directory in dirs
                if not should_ignore_workspace_path(
                    os.path.join(root, directory),
                    workspace_path,
                )
            )

            relative_root = os.path.relpath(root, workspace_path)
            if relative_root == ".":
                depth = 0
            else:
                depth = relative_root.count(os.sep) + 1
                lines.append(
                    f"{'    ' * (depth - 1)}|-- {os.path.basename(root)}/"
                )

            for file_name in sorted(files):
                if should_ignore_workspace_path(os.path.join(root, file_name), workspace_path):
                    continue
                lines.append(f"{'    ' * depth}|-- {file_name}")

        return "\n".join(lines)

    async def _auto_resolve_completed_tasks(self, brain_content):
        read_context = get_db()
        read_db = next(read_context)
        try:
            workspace = read_db.execute(
                select(Workspace).where(Workspace.local_path == os.path.abspath(self.target_dir))
            ).scalar_one_or_none()
            if workspace is None:
                return []

            active_tasks = read_db.execute(
                select(Task)
                .where(
                    Task.workspace_id == workspace.id,
                    Task.status != "done",
                )
                .order_by(Task.id.asc())
            ).scalars().all()
            workspace_id = workspace.id
            task_payload = [
                {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                }
                for task in active_tasks
            ]
        except Exception as exception:
            print(f">>> [QA LEAD] Task query failed: {exception}")
            return []
        finally:
            read_context.close()

        if not task_payload:
            return []

        qa_prompt = (
            "You are the QA Lead. Here is the updated project architecture:\n"
            f"{brain_content}\n\n"
            "Here are the active tasks:\n"
            f"{json.dumps(task_payload, ensure_ascii=True, indent=2)}\n\n"
            "Based strictly on the architecture changes, which task IDs have been "
            "successfully implemented? Return ONLY a JSON array of integers "
            "(e.g., [1, 4])."
        )

        loop = asyncio.get_running_loop()
        print(
            ">>> [QA AGENT] Evaluating active tasks against new architecture...",
            flush=True,
        )
        try:
            timeout_seconds = calculate_prompt_timeout(qa_prompt)
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._call_ai(
                        qa_prompt,
                        task_profile="fast",
                        agent_role="qa_agent",
                    ),
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            print(
                ">>> [QA LEAD] Completion check timed out after {} seconds.".format(
                    timeout_seconds
                )
            )
            return []
        except Exception as exception:
            print(f">>> [QA LEAD] Completion check failed: {exception}")
            return []

        raw_response = result.get("data", "")
        print(f">>> [QA AGENT] Raw AI Response: {raw_response}", flush=True)

        if result.get("status") != "success":
            print(f">>> [QA LEAD] Completion check failed: {result.get('message', 'Unknown error.')}")
            return []

        completed_ids = extract_json_int_array(raw_response)
        active_ids = {task["id"] for task in task_payload}
        invalid_ids = sorted({task_id for task_id in completed_ids if task_id not in active_ids})
        if invalid_ids:
            print(f">>> [QA LEAD] Ignoring invalid completed task IDs: {invalid_ids}")

        resolved_ids = sorted({task_id for task_id in completed_ids if task_id in active_ids})
        if not resolved_ids:
            return []

        write_context = get_db()
        write_db = next(write_context)
        try:
            completed_tasks = write_db.execute(
                select(Task).where(
                    Task.workspace_id == workspace_id,
                    Task.id.in_(resolved_ids),
                    Task.status != "done",
                )
            ).scalars().all()
            for task in completed_tasks:
                task.status = "done"
            write_db.commit()
            completed_task_ids = [task.id for task in completed_tasks]
            print(f">>> [QA LEAD] Completed task IDs: {completed_task_ids}")
            return completed_task_ids
        except Exception as exception:
            write_db.rollback()
            print(f">>> [QA LEAD] Task update failed: {exception}")
            return []
        finally:
            write_context.close()

    async def rebuild_brain(self):
        print(">>> [CARTOGRAPHER] Firing rebuild...")
        print(">>> [CARTOGRAPHER] Rebuilding brain...")
        if not self._brain_lock.acquire(blocking=False):
            print(">>> [CARTOGRAPHER] Rebuild skipped: already running.")
            return {"status": "skipped", "message": "Cartographer rebuild already running."}

        workspace_path = os.path.abspath(self.target_dir)
        try:
            print(f">>> [CARTOGRAPHER] Workspace root: {workspace_path}")
            tree = self._build_workspace_tree(workspace_path)
            prompt = (
                f"{CARTOGRAPHER_PROMPT}\n\n"
                f"Directory tree for `{os.path.basename(workspace_path)}`:\n"
                f"```text\n{tree}\n```"
            )

            loop = asyncio.get_running_loop()
            print(">>> [CARTOGRAPHER] Calling AI...")
            try:
                timeout_seconds = calculate_prompt_timeout(prompt)
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._call_ai(
                            prompt,
                            task_profile="fast",
                            agent_role="cartographer",
                        ),
                    ),
                    timeout=timeout_seconds,
                )
            except Exception as exception:
                print(">>> [CARTOGRAPHER] AI Fail")
                print(str(exception))
                return {"status": "error", "message": str(exception)}

            if result.get("status") != "success":
                print(">>> [CARTOGRAPHER] AI Fail")
                print(result.get("message", "Unknown AI failure."))
                return result

            print(">>> [CARTOGRAPHER] AI Success")
            brain_dir = os.path.abspath(os.path.join(workspace_path, ".nexus"))
            brain_path = os.path.abspath(os.path.join(brain_dir, "brain.md"))
            os.makedirs(brain_dir, exist_ok=True)
            with open(brain_path, "w", encoding="utf-8") as file:
                file.write(result["data"])
            print(f">>> [CARTOGRAPHER] Brain written: {brain_path}")
            completed_task_ids = await self._auto_resolve_completed_tasks(result["data"])

            return {
                "status": "success",
                "file": brain_path,
                "provider": result.get("provider"),
                "model": result.get("model"),
                "completed_task_ids": completed_task_ids,
            }
        except Exception as exception:
            print(f">>> [CARTOGRAPHER] Error: {exception}")
            print(f">>> [CARTOGRAPHER] Rebuild failed: {exception}")
            return {"status": "error", "message": str(exception)}
        finally:
            self._brain_lock.release()

    def _read_file(self, rel_path):
        full_path = os.path.join(self.target_dir, rel_path)
        if not os.path.exists(full_path):
            return None

        try:
            with open(full_path, "r", encoding="utf-8") as file:
                return file.read()
        except Exception:
            return None

    def _minify_text(self, content):
        return "\n".join([line for line in content.splitlines() if line.strip()])

    def _sorted_project_paths(self):
        return sorted(self.state["files"].keys())

    def _get_full_codebase(self, filter_role=None):
        full_code = ""

        for rel_path, info in self.state["files"].items():
            if filter_role and info["role"] not in filter_role:
                continue

            content = self._read_file(rel_path)
            if content is None:
                continue

            full_code += f"\n--- FILE: {rel_path} ---\n{self._minify_text(content)}\n"

        return full_code

    def _get_selected_codebase(self, file_paths):
        sections = []

        for rel_path in file_paths:
            content = self._read_file(rel_path)
            if content is None:
                continue

            sections.append(f"--- FILE: {rel_path} ---\n{content}\n")

        return "\n".join(sections)

    def generate_gem_context(self):
        prompt = prompts.get_gem_context_prompt(self._get_full_codebase())
        task_profile = TaskRouter.resolve_profile(tool_type="gem_context")
        return self._call_ai(
            prompt,
            task_profile=task_profile,
            out_filename="AI_GEM_CONTEXT.md",
        )

    def profile_user_habits(self, workspace_id):
        read_context = get_db()
        read_db = next(read_context)
        try:
            footprints = read_db.execute(
                select(Footprint)
                .where(Footprint.workspace_id == workspace_id)
                .order_by(Footprint.created_at.desc(), Footprint.id.desc())
                .limit(20)
            ).scalars().all()
        except Exception as exception:
            return {"status": "error", "message": str(exception)}
        finally:
            read_context.close()

        logs = [
            {
                "persona": footprint.persona,
                "action_type": footprint.action_type,
                "content": footprint.content,
                "created_at": (
                    footprint.created_at.isoformat()
                    if footprint.created_at
                    else None
                ),
            }
            for footprint in footprints
        ]
        prompt = (
            "Analyze these logs and extract the user's technical preferences, "
            "framework choices, and workflow habits. Return ONLY a valid JSON "
            "object of key-value string pairs.\n\n"
            f"Logs:\n{json.dumps(logs, ensure_ascii=True, indent=2)}"
        )
        result = self._call_ai(prompt, task_profile="fast")
        if result.get("status") != "success":
            return result

        try:
            preferences = json.loads(result["data"])
        except (TypeError, ValueError) as exception:
            return {
                "status": "error",
                "message": f"Profiler returned invalid JSON: {exception}",
            }

        if not isinstance(preferences, dict) or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str)
            for key, value in preferences.items()
        ):
            return {
                "status": "error",
                "message": "Profiler response must be an object of string key-value pairs.",
            }

        write_context = get_db()
        write_db = next(write_context)
        try:
            for key, value in preferences.items():
                profile = write_db.execute(
                    select(UserProfile).where(UserProfile.preference_key == key)
                ).scalar_one_or_none()
                if profile is None:
                    write_db.add(
                        UserProfile(
                            preference_key=key,
                            preference_value=value,
                        )
                    )
                else:
                    profile.preference_value = value

            write_db.commit()
            return {
                "status": "success",
                "message": "CTO profile synchronized.",
                "updated_count": len(preferences),
                "preferences": preferences,
            }
        except Exception as exception:
            write_db.rollback()
            return {"status": "error", "message": str(exception)}
        finally:
            write_context.close()

    def run_ai_tool(self, tool_type):
        tool_type = (tool_type or "").strip().lower()
        task_profile = TaskRouter.resolve_profile(tool_type=tool_type)

        if tool_type == "audit":
            prompt = prompts.get_audit_prompt(self._get_full_codebase())
            return self._call_ai(
                prompt,
                task_profile=task_profile,
                out_filename="AI_SECURITY_AUDIT.md",
            )

        if tool_type == "erd":
            prompt = prompts.get_erd_prompt(
                self._get_full_codebase(filter_role=["model", "migration"])
            )
            return self._call_ai(
                prompt,
                task_profile=task_profile,
                out_filename="DATABASE_ERD.md",
            )

        return {"status": "error", "message": "Unknown tool type."}

    def build_chat_bundle(self, message="", selected_paths=None, mode="task"):
        return self.chat_bundle_builder.build(
            state=self.state,
            message=message,
            selected_paths=selected_paths or [],
            mode=mode,
            max_related_files=12,
            include_context=True,
            include_recent_changes=True,
        )

    def build_full_minified_bundle(self):
        out_file = os.path.join(self.out_dir, "full_minified_bundle.txt")
        file_count = 0

        with open(out_file, "w", encoding="utf-8") as outfile:
            outfile.write("=== NEXUS FULL MINIFIED BUNDLE ===\n")
            outfile.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            outfile.write(f"Target Dir: {self.target_dir}\n\n")

            for rel_path in self._sorted_project_paths():
                content = self._read_file(rel_path)
                if content is None:
                    continue

                minified = self._minify_text(content)
                outfile.write(f"--- FILE: {rel_path} ---\n{minified}\n\n")
                file_count += 1

        return {
            "status": "success",
            "file": "output/full_minified_bundle.txt",
            "file_count": file_count,
        }

    def get_context_path(self, rel_path):
        safe_name = rel_path.replace("/", "___").replace("\\", "___") + ".md"
        return os.path.join(self.context_dir, safe_name)

    def read_context(self, rel_path):
        md_path = self.get_context_path(rel_path)
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as file:
                return file.read()
        return None

    def build_ai_context(self, rel_path):
        full_path = os.path.join(self.target_dir, rel_path)
        if not os.path.exists(full_path):
            return {"status": "error", "message": "File not found."}

        try:
            with open(full_path, "r", encoding="utf-8") as file:
                code_content = file.read()

            prompt = prompts.get_context_prompt(
                rel_path=rel_path,
                filename=os.path.basename(rel_path),
                code_content=code_content,
            )

            task_profile = TaskRouter.resolve_profile(tool_type="context")
            return self._call_ai(
                prompt,
                task_profile=task_profile,
                is_context=True,
                rel_path=rel_path,
            )
        except Exception as exception:
            return {"status": "error", "message": str(exception)}

    def chat(self, session_id, message, selected_paths=None, mode="ask", known_preferences=""):
        selected_paths = selected_paths or []
        history = self.chat_store.get_history(session_id)
        selected_code = self._get_selected_codebase(selected_paths)
        task_profile = TaskRouter.resolve_profile(mode=mode, tool_type="chat")

        prompt = prompts.get_chat_prompt(
            message=message,
            mode=mode,
            selected_paths=selected_paths,
            selected_code=selected_code,
            project_state=self._get_project_state_summary(),
            history=history,
            known_preferences=known_preferences,
            architecture_mmd=self._read_architecture_mmd() if mode == "tech_lead" else "",
        )

        result = self._call_ai(
            prompt,
            task_profile=task_profile,
            agent_role=mode,
        )

        if result["status"] != "success":
            return result

        assistant_message = result["data"]
        self.chat_store.append_exchange(
            session_id=session_id,
            user_message=message,
            assistant_message=assistant_message,
        )

        return {
            "status": "success",
            "message": assistant_message,
            "provider": result.get("provider"),
            "model": result.get("model"),
            "task_profile": result.get("task_profile"),
            "selection_mode": result.get("selection_mode"),
        }

    def chat_stream(
        self,
        session_id,
        message,
        selected_paths=None,
        mode="ask",
        known_preferences="",
    ):
        start_time = time.monotonic()
        timeout_seconds = None
        try:
            selected_paths = selected_paths or []
            history = self.chat_store.get_history(session_id)
            selected_code = self._get_selected_codebase(selected_paths)
            task_profile = TaskRouter.resolve_profile(mode=mode, tool_type="chat")

            prompt = prompts.get_chat_prompt(
                message=message,
                mode=mode,
                selected_paths=selected_paths,
                selected_code=selected_code,
                project_state=self._get_project_state_summary(),
                history=history,
                known_preferences=known_preferences,
                architecture_mmd=self._read_architecture_mmd() if mode == "tech_lead" else "",
            )

            resolved = self.resolve_agent_model(mode, fallback_profile=task_profile)
            client = self._build_client(resolved["provider"])
            assistant_chunks = []
            timeout_seconds = calculate_prompt_timeout(prompt)
            start_time = time.monotonic()

            for chunk in client.generate_stream(
                prompt,
                model=resolved["model"],
                timeout=timeout_seconds,
            ):
                if not chunk:
                    continue
                assistant_chunks.append(chunk)
                yield chunk

            self.chat_store.append_exchange(
                session_id=session_id,
                user_message=message,
                assistant_message="".join(assistant_chunks),
            )
            self._log_telemetry(
                {
                    "action": "ai_generate_stream",
                    "provider": resolved["provider"],
                    "model": resolved["model"],
                    "execution_time": round(time.monotonic() - start_time, 3),
                    "return_code": 0,
                    "timeout_seconds": timeout_seconds,
                    "token_usage": None,
                    "stderr": "",
                    "error": "",
                }
            )
        except Exception as exception:
            self._log_telemetry(
                {
                    "action": "ai_generate_stream",
                    "execution_time": round(time.monotonic() - start_time, 3),
                    "return_code": 1,
                    "timeout_seconds": timeout_seconds,
                    "token_usage": None,
                    "stderr": str(exception),
                    "error": str(exception),
                }
            )
            yield f"Error: {exception}"

    def _read_architecture_mmd(self):
        architecture_path = os.path.join(self.target_dir, ".nexus", "architecture.mmd")
        try:
            with open(architecture_path, "r", encoding="utf-8") as file:
                return file.read()
        except OSError:
            return ""

    def _get_project_state_summary(self):
        file_count = len(self.state["files"])
        route_count = len(self.state["routes"])
        recent_changes = self.state["recent_changes"][:5]

        summary = {
            "file_count": file_count,
            "route_count": route_count,
            "recent_changes": recent_changes,
        }

        return json.dumps(summary, indent=2)

    def bundle_self(self):
        out_file = os.path.join(self.out_dir, "nexus_source_dump.txt")
        source_files = [
            "bundle.py",
            "engine.py",
            "dashboard.py",
            "prompts.py",
            "chat_session_store.py",
            "model_registry.py",
            "task_router.py",
            "bundle_builders/chat_bundle_builder.py",
            "static/js/core.js",
            "static/js/settings.js",
            "static/js/explorer.js",
            "static/js/inspector.js",
            "static/js/scripts.js",
            "static/js/chat.js",
            "static/js/map.js",
            "static/js/app.js",
            "static/style.css",
            "templates/index.html",
            "ai_clients/base.py",
            "ai_clients/gemini_client.py",
            "ai_clients/openai_client.py",
            "ai_clients/factory.py",
        ]

        with open(out_file, "w", encoding="utf-8") as outfile:
            outfile.write("--- NEXUS OS SELF-DUMP ---\n")
            outfile.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            for rel_path in source_files:
                full_path = os.path.join(self.pbund_dir, rel_path)
                if not os.path.exists(full_path):
                    continue

                try:
                    with open(full_path, "r", encoding="utf-8") as file:
                        outfile.write(f"--- FILE: {rel_path} ---\n{file.read()}\n\n")
                except Exception:
                    pass

        return out_file

    def identify_context(self, rel_path):
        path_norm = rel_path.replace("\\", "/")
        role = "utility"

        for role_name, pattern in ROLE_MAP:
            if re.search(pattern, path_norm):
                role = role_name
                break

        if role in {
            "controller",
            "model",
            "service",
            "middleware",
            "request",
            "provider",
            "route",
            "migration",
        }:
            return "backend", role

        if role in {"vue", "blade"} or any(
            part in path_norm for part in ["resources/", "public/"]
        ):
            return "frontend", role

        return "other", role

    def parse_laravel_routes(self):
        routes = []
        web_path = os.path.join(self.target_dir, "routes", "web.php")

        if not os.path.exists(web_path):
            return routes

        try:
            with open(web_path, "r", encoding="utf-8") as file:
                content = file.read()

            matches = re.findall(
                r"Route::\w+\(['\"]/(.*?)['\"],\s*\[(.*?)::class,\s*['\"](.*?)['\"]\]",
                content,
            )

            for path, controller, method in matches:
                routes.append(
                    {
                        "path": f"/{path}",
                        "controller": controller,
                        "method": method,
                    }
                )
        except Exception:
            pass

        return routes

    def bundle_focused(self, file_paths):
        out_file = os.path.join(self.out_dir, "focused_bundle.txt")

        with open(out_file, "w", encoding="utf-8") as outfile:
            for rel_path in file_paths:
                content = self._read_file(rel_path)
                if content is None:
                    continue

                minified = self._minify_text(content)
                outfile.write(f"--- FILE: {rel_path} ---\n{minified}\n\n")

        return out_file

    def run_analysis(self, modified_file=None):
        if modified_file:
            rel_mod = os.path.relpath(modified_file, self.target_dir)
            if rel_mod not in self.state["recent_changes"]:
                self.state["recent_changes"].insert(0, rel_mod)
                self.state["recent_changes"] = self.state["recent_changes"][:5]

        new_files = {}
        relations = {}

        for root, dirs, files in os.walk(self.target_dir):
            dirs[:] = [
                directory
                for directory in dirs
                if not should_ignore_workspace_path(
                    os.path.join(root, directory),
                    self.target_dir,
                )
            ]

            for file_name in files:
                full_path = os.path.join(root, file_name)
                if should_ignore_workspace_path(full_path, self.target_dir):
                    continue

                rel_path = os.path.relpath(full_path, self.target_dir)
                layer, role = self.identify_context(rel_path)

                try:
                    with open(full_path, "r", encoding="utf-8") as file:
                        content = file.read()

                    lines = content.splitlines()
                    deps = re.findall(r"(?:use|import)\s+([^;'\"]+)", content)

                    if rel_path.endswith(".php"):
                        signatures = [
                            line.strip()
                            for line in lines
                            if re.match(
                                r"^\s*(public|protected|private|static)?\s*function\s+\w+",
                                line,
                            )
                        ]
                    elif rel_path.endswith(".vue"):
                        signatures = [
                            line.strip()
                            for line in lines
                            if re.search(r"(props|methods|data|computed|setup)\s*[:\(]", line)
                        ]
                    else:
                        signatures = [
                            line.strip()
                            for line in lines
                            if re.match(r"^\s*(async\s+)?(function|const|let|class)\s+\w+", line)
                        ]

                    new_files[rel_path] = {
                        "layer": layer,
                        "role": role,
                        "line_count": len(lines),
                        "signatures": signatures[:30],
                        "has_context": os.path.exists(self.get_context_path(rel_path)),
                    }
                    relations[rel_path] = [
                        dependency.strip().split("\\")[-1].split("/")[-1]
                        for dependency in deps
                    ]
                except Exception:
                    pass

        self.state.update(
            {
                "files": new_files,
                "relations": relations,
                "routes": self.parse_laravel_routes(),
                "last_update": time.strftime("%H:%M:%S"),
            }
        )


class NexusWatcher(FileSystemEventHandler):
    def __init__(self, engine):
        self.engine = engine
        self.debounce = None
        self._debounce_generation = 0
        self._debounce_lock = Lock()
        print(
            f">>> [WATCHDOG BOOT] Actively watching directory: "
            f"{os.path.abspath(self.engine.target_dir)}"
        )

    def _get_ignore_patterns(self):
        patterns = list(IGNORE_PATTERNS)
        nexusignore_path = os.path.join(self.engine.target_dir, ".nexusignore")

        try:
            with open(nexusignore_path, "r", encoding="utf-8") as file:
                patterns.extend(
                    line.strip()
                    for line in file
                    if line.strip() and not line.lstrip().startswith("#")
                )
        except OSError:
            pass

        return patterns

    def _should_ignore(self, file_path):
        if should_ignore_workspace_path(file_path, self.engine.target_dir):
            return True

        normalized_path = os.path.abspath(file_path).replace(os.sep, "/")
        return any(
            pattern.replace(os.sep, "/") in normalized_path
            for pattern in self._get_ignore_patterns()
        )

    def _handle_change(self, event, event_type):
        file_path = os.path.abspath(event.src_path)
        print(f">>> [WATCHDOG EVENT] File {event_type}: {file_path}")
        print(f">>> [WATCHDOG] File changed: {file_path}")
        if event.is_directory:
            print(">>> [WATCHDOG] Ignoring directory event.")
            return

        if self._should_ignore(file_path):
            print(f">>> [WATCHDOG] Ignored (Cost Control): {file_path}")
            return

        generated_paths = {
            os.path.abspath(os.path.join(self.engine.target_dir, ".nexus", "brain.md")),
            os.path.abspath(os.path.join(self.engine.target_dir, ".nexus", "architecture.mmd")),
        }
        if file_path in generated_paths:
            print(f">>> [WATCHDOG] Ignoring generated artifact update: {file_path}")
            return

        with self._debounce_lock:
            self._debounce_generation += 1
            generation = self._debounce_generation
            if self.debounce:
                print(">>> [WATCHDOG] Resetting rebuild debounce timer.")
                self.debounce.cancel()

            print(f">>> [WATCHDOG] Queuing rebuild for: {file_path}")
            self.debounce = Timer(
                WATCHDOG_DEBOUNCE_SECONDS,
                self._process_change,
                [file_path, generation],
            )
            self.debounce.daemon = True
            self.debounce.start()

    def on_modified(self, event):
        print(f">>> [WATCHDOG] Detected change in: {os.path.abspath(event.src_path)}", flush=True)
        self._handle_change(event, "modified")

    def on_created(self, event):
        print(f">>> [WATCHDOG] Detected change in: {os.path.abspath(event.src_path)}", flush=True)
        self._handle_change(event, "created")

    def on_moved(self, event):
        source_path = os.path.abspath(event.src_path)
        destination_path = os.path.abspath(event.dest_path)
        print(f">>> [WATCHDOG] Detected move from: {source_path} to: {destination_path}", flush=True)

        if event.is_directory:
            print(">>> [WATCHDOG] Ignoring directory move event.")
            return

        if self._should_ignore(source_path) or self._should_ignore(destination_path):
            print(
                f">>> [WATCHDOG] Ignored move (Cost Control): "
                f"{source_path} -> {destination_path}"
            )
            return

        with self._debounce_lock:
            self._debounce_generation += 1
            generation = self._debounce_generation
            if self.debounce:
                print(">>> [WATCHDOG] Resetting rebuild debounce timer.")
                self.debounce.cancel()

            print(f">>> [WATCHDOG] Queuing rebuild for: {destination_path}")
            self.debounce = Timer(
                WATCHDOG_DEBOUNCE_SECONDS,
                self._process_change,
                [destination_path, generation],
            )
            self.debounce.daemon = True
            self.debounce.start()

    def _process_change(self, source_path, generation):
        with self._debounce_lock:
            if generation != self._debounce_generation:
                return
            self.debounce = None

        if self._should_ignore(source_path):
            print(f">>> [WATCHDOG] Ignored (Cost Control): {source_path}")
            return

        print(f">>> [WATCHDOG] Processing change: {source_path}")
        try:
            self.engine.run_analysis(source_path)
        except Exception as exception:
            print(f"File analysis failed: {exception}")

        try:
            result = asyncio.run(self.engine.rebuild_brain())
            if result.get("status") == "error":
                print(f"Cartographer rebuild failed: {result['message']}")
            elif result.get("status") == "skipped":
                print(f">>> [CARTOGRAPHER] {result['message']}")
        except Exception as exception:
            print(f"Cartographer rebuild failed: {exception}")
