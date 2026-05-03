import json
import os
import re
import time

import prompts
from ai_clients.factory import AIClientFactory
from bundle_builders.chat_bundle_builder import ChatBundleBuilder
from chat_session_store import ChatSessionStore
from model_registry import ModelRegistry
from task_router import TaskRouter
from threading import Timer
from watchdog.events import FileSystemEventHandler


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


class NexusEngine:
    def __init__(self, target_dir):
        self.target_dir = os.path.abspath(target_dir)
        self.pbund_dir = os.path.dirname(os.path.abspath(__file__))
        self.out_dir = os.path.join(self.pbund_dir, "output")
        self.context_dir = os.path.join(self.pbund_dir, "context")
        self.settings_file = os.path.join(self.pbund_dir, "settings.json")

        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.context_dir, exist_ok=True)

        self.state = {
            "files": {},
            "relations": {},
            "routes": [],
            "recent_changes": [],
            "last_update": "Never",
        }

        self.settings = self.load_settings()
        self.chat_store = ChatSessionStore(max_messages=20)
        self.chat_bundle_builder = ChatBundleBuilder(
            target_dir=self.target_dir,
            output_dir=self.out_dir,
            context_dir=self.context_dir,
        )
        self.model_registry = ModelRegistry(self.settings)

    def load_settings(self):
        defaults = {
            "provider": "auto",
            "gemini_api_key": "",
            "gemini_model": "",
            "openai_api_key": "",
            "openai_model": "",
            "model_selection_mode": "auto",
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

        if not defaults["gemini_api_key"]:
            defaults["gemini_api_key"] = os.getenv("GEMINI_API_KEY", "")

        if not defaults["openai_api_key"]:
            defaults["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")

        if defaults["model_selection_mode"] not in {"auto", "manual"}:
            defaults["model_selection_mode"] = "auto"

        return defaults

    def save_settings(self, new_settings):
        allowed_keys = {
            "provider",
            "gemini_api_key",
            "gemini_model",
            "openai_api_key",
            "openai_model",
            "model_selection_mode",
        }

        for key, value in new_settings.items():
            if key in allowed_keys:
                self.settings[key] = value

        provider = (self.settings.get("provider") or "auto").strip().lower()
        if provider not in {"auto", "gemini", "openai"}:
            self.settings["provider"] = "auto"

        mode = (self.settings.get("model_selection_mode") or "auto").strip().lower()
        if mode not in {"auto", "manual"}:
            self.settings["model_selection_mode"] = "auto"

        with open(self.settings_file, "w", encoding="utf-8") as file:
            json.dump(self.settings, file, indent=2)

        self.model_registry = ModelRegistry(self.settings)

        return {"status": "success", "settings": self.settings}

    def list_models(self, provider=None, force=False):
        return self.model_registry.refresh(provider=provider, force=force)

    def list_curated_models(self, provider=None):
        return self.model_registry.get_curated_catalog(provider=provider)

    def resolve_model(self, task_profile="balanced", provider_override=None):
        selection_mode = (self.settings.get("model_selection_mode") or "auto").strip().lower()

        manual_overrides = {}
        if selection_mode == "manual":
            manual_overrides = {
                "gemini": (self.settings.get("gemini_model") or "").strip(),
                "openai": (self.settings.get("openai_model") or "").strip(),
            }

        provider_preference = provider_override or self.settings.get("provider") or "auto"

        return self.model_registry.choose(
            task_profile=task_profile,
            provider_preference=provider_preference,
            manual_overrides=manual_overrides,
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
    ):
        try:
            resolved = self.resolve_model(
                task_profile=task_profile,
                provider_override=provider_override,
            )

            provider = resolved["provider"]
            model = resolved["model"]

            client = self._build_client(provider)
            result = client.generate(prompt, model=model)

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
                    "task_profile": task_profile,
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
                    "task_profile": task_profile,
                    "selection_mode": resolved.get("selection_mode"),
                }

            return {
                "status": "success",
                "data": text,
                "provider": provider,
                "model": result["model"],
                "task_profile": task_profile,
                "selection_mode": resolved.get("selection_mode"),
            }
        except Exception as exception:
            return {
                "status": "error",
                "message": str(exception),
            }

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

    def chat(self, session_id, message, selected_paths=None, mode="ask"):
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
        )

        result = self._call_ai(
            prompt,
            task_profile=task_profile,
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
            dirs[:] = [directory for directory in dirs if directory not in EXCLUDE_DIRS]

            for file_name in files:
                extension = os.path.splitext(file_name)[1].lower()
                if extension in EXCLUDE_EXTS:
                    continue

                full_path = os.path.join(root, file_name)
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

    def on_modified(self, event):
        if event.is_directory or "pbund" in event.src_path:
            return

        if self.debounce:
            self.debounce.cancel()

        self.debounce = Timer(1.0, self.engine.run_analysis, [event.src_path])
        self.debounce.start()
