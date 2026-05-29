import os
import re
import shutil
import subprocess
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import dashboard as dashboard_module  # noqa: E402
import engine as engine_module  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from engine import NexusEngine  # noqa: E402
from models import Base, PromptTemplate  # noqa: E402
from src.services import prompt_vault  # noqa: E402


FAILURES = []


class NoopChatSessionStore:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages

    def get_history(self, session_id):
        return []

    def append_exchange(self, session_id, user_message, assistant_message):
        return None


def check(condition, message):
    if condition:
        print("PASS: {}".format(message))
        return
    print("FAIL: {}".format(message))
    FAILURES.append(message)


def read_file(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def section_between(content, start, end):
    start_index = content.find(start)
    if start_index == -1:
        return ""
    end_index = content.find(end, start_index + len(start))
    if end_index == -1:
        return content[start_index:]
    return content[start_index:end_index]


def verify_docs():
    required = {
        "docs/WORKFLOW_LOCK.md": ["Prompt Vault", "one_packet", "no force push"],
        "docs/SPRINT_PLAN.md": ["Supervised Factory Alpha", "Prompt Vault"],
        "docs/PROMPTING_GUIDE.md": ["Codex operator prompt", "Prompt Vault"],
        "docs/PROMPT_TEMPLATES.md": ["Live Smoke Test Packet", "Prompt Templates"],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_model_and_service():
    fields = (
        "title",
        "category",
        "risk_level",
        "description",
        "body",
        "variables_json",
        "tags_json",
        "status",
        "success_count",
        "failure_count",
        "last_used_at",
        "created_at",
        "updated_at",
    )
    for field in fields:
        check(hasattr(PromptTemplate, field), "PromptTemplate has {}".format(field))

    templates = prompt_vault.default_prompt_templates()
    categories = set(template.get("category") for template in templates)
    check(len(templates) >= 7, "default_prompt_templates returns at least 7 templates")
    for category in ("feature", "bugfix", "uiux", "testing", "schema"):
        check(category in categories, "default templates include {} category".format(category))
    check(callable(prompt_vault.ensure_default_prompt_templates), "prompt vault service imports")


def make_client(session_factory):
    original_get_db = dashboard_module.get_db
    original_chat_store = engine_module.ChatSessionStore

    def get_test_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    dashboard_module.get_db = get_test_db
    engine_module.ChatSessionStore = NoopChatSessionStore
    engine = NexusEngine(PROJECT_ROOT)
    dashboard = NexusDashboard(engine)
    dashboard.app.config["TESTING"] = True
    engine_module.ChatSessionStore = original_chat_store
    return dashboard.app.test_client(), original_get_db


def verify_prompt_vault_routes():
    sqlite_engine = create_engine("sqlite:///:memory:")
    PromptTemplate.__table__.create(bind=sqlite_engine)
    session_factory = sessionmaker(bind=sqlite_engine)
    client, original_get_db = make_client(session_factory)
    try:
        response = client.get("/api/prompt-vault/templates")
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET prompt templates HTTP 200")
        check(payload.get("status") == "success", "GET prompt templates success")
        check(len(payload.get("templates") or []) >= 7, "GET prompt templates seeds starters")

        response = client.post(
            "/api/prompt-vault/templates",
            json={
                "title": "Packet 021 Test Template",
                "category": "feature",
                "risk_level": "low",
                "description": "test template",
                "body": "MISSION:\nTest prompt vault route.",
                "variables": {"packet": "021"},
                "tags": ["test", "prompt-vault"],
            },
        )
        created = response.get_json(silent=True) or {}
        template_id = (created.get("template") or {}).get("id")
        check(response.status_code == 201, "POST prompt template HTTP 201")
        check(created.get("status") == "success", "POST prompt template success")
        check(bool(template_id), "POST prompt template returns id")

        response = client.get("/api/prompt-vault/templates/{}".format(template_id))
        detail = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET prompt template detail HTTP 200")
        check((detail.get("template") or {}).get("title") == "Packet 021 Test Template", "GET prompt detail returns created template")

        response = client.put(
            "/api/prompt-vault/templates/{}".format(template_id),
            json={"description": "updated", "tags": ["updated"]},
        )
        updated = response.get_json(silent=True) or {}
        check(response.status_code == 200, "PUT prompt template HTTP 200")
        check((updated.get("template") or {}).get("description") == "updated", "PUT prompt template updates description")

        response = client.post(
            "/api/prompt-vault/templates/{}/mark-used".format(template_id),
            json={"result": "success"},
        )
        used = response.get_json(silent=True) or {}
        check(response.status_code == 200, "mark-used prompt template HTTP 200")
        check((used.get("template") or {}).get("success_count") == 1, "mark-used increments success count")

        response = client.post("/api/prompt-vault/templates/{}/archive".format(template_id))
        archived = response.get_json(silent=True) or {}
        check(response.status_code == 200, "archive prompt template HTTP 200")
        check((archived.get("template") or {}).get("status") == "archived", "archive prompt template sets archived")
    finally:
        dashboard_module.get_db = original_get_db


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    schema_sync = read_file("scripts/sync_factory_schema.py")
    prompt_service = read_file("src/services/prompt_vault.py")

    for marker in (
        "/api/prompt-vault/templates",
        "ensure_default_prompt_templates",
        "archive_prompt_template",
        "mark_prompt_template_used",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in ("Prompt Vault", "/api/prompt-vault/templates", "Copy Template", "Category Filter"):
        check(marker in app_js + template, "frontend contains {}".format(marker))

    check("prompt_templates" in schema_sync, "schema sync mentions prompt_templates")
    check("PromptTemplate" in read_file("models.py"), "models.py mentions PromptTemplate")

    prompt_api_section = section_between(dashboard, "/api/prompt-vault/templates", "/api/kill-process")
    prompt_ui_section = section_between(app_js, "async loadPromptVaultTemplates", "async copyCodexCommand")
    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in prompt_api_section, "prompt vault backend avoids {}".format(route))
        check(route not in prompt_ui_section, "prompt vault frontend avoids {}".format(route))

    check("shell" + "=True" not in dashboard + prompt_service, "prompt vault code avoids shell true assignment")
    check("subprocess." + "Popen" not in dashboard + prompt_service, "prompt vault code avoids subprocess popen")
    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_key_pattern.search(app_js), "no raw frontend API key reads")


def verify_node_check():
    if shutil.which("node") is None:
        print("PASS: node --check skipped because node is unavailable")
        return
    result = subprocess.run(
        ["node", "--check", "static/js/app.js"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    check(result.returncode == 0, "node --check static/js/app.js")


def main():
    verify_docs()
    verify_model_and_service()
    verify_prompt_vault_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 021 verification failed")
        return 1
    print("PASS: Packet 021 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
