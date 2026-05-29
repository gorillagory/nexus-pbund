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
from models import OrchestrationInboxItem, Workspace  # noqa: E402
from src.services import orchestration_inbox  # noqa: E402


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
        "docs/WORKFLOW_LOCK.md": ["Orchestration Inbox", "Do not execute from capture", "Packet 022"],
        "docs/SPRINT_PLAN.md": ["Packet 022 Orchestration Inbox foundation", "Inbox capture rule"],
        "docs/CHAT_HANDOFF.md": ["Orchestration Inbox", "Packet 022"],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_model_and_service():
    fields = (
        "id",
        "workspace_id",
        "title",
        "raw_intent",
        "source",
        "status",
        "priority",
        "category",
        "triage_notes",
        "created_at",
        "updated_at",
    )
    for field in fields:
        check(hasattr(OrchestrationInboxItem, field), "OrchestrationInboxItem has {}".format(field))

    check("captured" in orchestration_inbox.INBOX_STATUSES, "inbox statuses include captured")
    check("triaged" in orchestration_inbox.INBOX_STATUSES, "inbox statuses include triaged")
    check("staged" in orchestration_inbox.INBOX_STATUSES, "inbox statuses include staged")
    check("discarded" in orchestration_inbox.INBOX_STATUSES, "inbox statuses include discarded")
    for helper in (
        "create_inbox_item",
        "list_inbox_items",
        "update_inbox_item",
        "discard_inbox_item",
        "serialize_inbox_item",
    ):
        check(callable(getattr(orchestration_inbox, helper, None)), "orchestration inbox service has {}".format(helper))


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


def verify_inbox_routes():
    sqlite_engine = create_engine("sqlite:///:memory:")
    Workspace.__table__.create(bind=sqlite_engine)
    OrchestrationInboxItem.__table__.create(bind=sqlite_engine)
    session_factory = sessionmaker(bind=sqlite_engine)
    session = session_factory()
    try:
        session.add(Workspace(name="Packet 022 Test", local_path=PROJECT_ROOT))
        session.commit()
    finally:
        session.close()

    client, original_get_db = make_client(session_factory)
    try:
        response = client.get("/api/orchestration-inbox/items")
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET inbox items HTTP 200")
        check(payload.get("status") == "success", "GET inbox items success")
        check(payload.get("items") == [], "GET inbox items starts empty")

        response = client.post(
            "/api/orchestration-inbox/items",
            json={
                "title": "Packet 022 captured idea",
                "raw_intent": "Capture this raw idea for later triage.",
                "priority": "high",
                "category": "feature",
            },
        )
        created = response.get_json(silent=True) or {}
        item = created.get("item") or {}
        item_id = item.get("id")
        check(response.status_code == 201, "POST inbox item HTTP 201")
        check(created.get("status") == "success", "POST inbox item success")
        check(bool(item_id), "POST inbox item returns id")
        check(item.get("status") == "captured", "POST inbox item defaults captured")
        check(item.get("source") == "manual", "POST inbox item defaults manual source")

        response = client.put(
            "/api/orchestration-inbox/items/{}".format(item_id),
            json={
                "status": "triaged",
                "priority": "normal",
                "category": "docs",
                "triage_notes": "Convert to a scoped docs update.",
            },
        )
        updated = response.get_json(silent=True) or {}
        updated_item = updated.get("item") or {}
        check(response.status_code == 200, "PUT inbox item HTTP 200")
        check(updated.get("status") == "success", "PUT inbox item success")
        check(updated_item.get("status") == "triaged", "PUT inbox item updates status")
        check(updated_item.get("triage_notes") == "Convert to a scoped docs update.", "PUT inbox item updates triage notes")

        response = client.get("/api/orchestration-inbox/items?status=triaged")
        filtered = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET filtered inbox items HTTP 200")
        check(len(filtered.get("items") or []) == 1, "GET filtered inbox items returns triaged item")

        response = client.post(
            "/api/orchestration-inbox/items/{}/discard".format(item_id),
            json={"triage_notes": "Explicitly discarded by operator."},
        )
        discarded = response.get_json(silent=True) or {}
        discarded_item = discarded.get("item") or {}
        check(response.status_code == 200, "discard inbox item HTTP 200")
        check(discarded.get("status") == "success", "discard inbox item success")
        check(discarded_item.get("status") == "discarded", "discard inbox item sets discarded")
    finally:
        dashboard_module.get_db = original_get_db


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    style = read_file("static/style.css")
    schema_sync = read_file("scripts/sync_factory_schema.py")
    service = read_file("src/services/orchestration_inbox.py")

    for marker in (
        "/api/orchestration-inbox/items",
        "create_inbox_item",
        "discard_inbox_item",
        "serialize_inbox_item",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in (
        "Orchestration Inbox",
        "Capture Idea",
        "Status Filter",
        "Save Triage",
        "NexusCore.confirmAction",
    ):
        check(marker in app_js + template, "frontend contains {}".format(marker))

    check("orchestration_inbox_items" in schema_sync, "schema sync mentions orchestration_inbox_items")
    check("OrchestrationInboxItem" in read_file("models.py"), "models.py mentions OrchestrationInboxItem")
    check("orchestration-inbox-list-item" in style, "style contains inbox list item class")

    inbox_api_section = section_between(dashboard, "/api/orchestration-inbox/items", "/api/prompt-vault/templates")
    inbox_ui_section = section_between(app_js, "async loadOrchestrationInboxItems", "async loadPromptVaultTemplates")
    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in inbox_api_section, "inbox backend avoids {}".format(route))
        check(route not in inbox_ui_section, "inbox frontend avoids {}".format(route))

    check("execution_mode" not in inbox_api_section, "inbox backend does not set execution mode")
    check("autopilot" not in inbox_api_section.lower(), "inbox backend avoids autopilot")
    check("alert(" not in inbox_ui_section, "inbox frontend avoids native alert")
    check("confirm(" not in inbox_ui_section, "inbox frontend avoids native confirm")
    check("shell" + "=True" not in dashboard + service, "inbox code avoids shell true assignment")
    check("subprocess." + "Popen" not in dashboard + service, "inbox code avoids subprocess popen")
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
    verify_inbox_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 022 verification failed")
        return 1
    print("PASS: Packet 022 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
