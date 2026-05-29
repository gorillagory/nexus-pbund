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
from src.services import discord_router  # noqa: E402


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
        "docs/WORKFLOW_LOCK.md": ["Discord Event Router", "source `discord`", "do not execute tasks"],
        "docs/SPRINT_PLAN.md": ["Packet 023 Discord Event Router foundation", "Discord router rule", "DISCORD_INGEST_SECRET"],
        "docs/CHAT_HANDOFF.md": ["Discord Event Router", "Packet 023"],
        ".env.example": ["DISCORD_ROUTER_ENABLED=false", "DISCORD_INGEST_SECRET="],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_service():
    payload = {
        "content": "Please add a safe operator handoff command.",
        "author": {"username": "operator"},
        "channel_id": "ops",
        "timestamp": "2026-05-30T00:00:00Z",
    }
    normalized = discord_router.normalize_discord_event(payload)
    check(normalized.get("source") == "discord", "normalizer sets source discord")
    check(normalized.get("category") == "discord", "normalizer sets category discord")
    check(normalized.get("priority") == "normal", "normalizer sets normal priority")
    check("Please add" in normalized.get("raw_intent", ""), "normalizer captures message content")
    check("operator" in normalized.get("triage_notes", ""), "normalizer records author metadata")
    fake_secret = "sk-" + "packet023secret"
    secret_payload = discord_router.normalize_discord_event(
        {"content": "Authorization: Bearer {} should be redacted.".format(fake_secret)}
    )
    check(fake_secret not in secret_payload.get("raw_intent", ""), "normalizer redacts secret-looking content")

    settings = {"discord_router_enabled": True, "discord_ingest_secret": "packet-023-secret-value"}
    check(discord_router.discord_router_status(settings).get("secret_configured") is True, "status reports secret configured")
    check("packet-023-secret-value" not in str(discord_router.discord_router_status(settings)), "status does not expose secret")


def make_client(session_factory, settings=None):
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
    if settings:
        engine.settings.update(settings)
    dashboard = NexusDashboard(engine)
    dashboard.app.config["TESTING"] = True
    engine_module.ChatSessionStore = original_chat_store
    return dashboard.app.test_client(), original_get_db, engine


def verify_routes():
    sqlite_engine = create_engine("sqlite:///:memory:")
    Workspace.__table__.create(bind=sqlite_engine)
    OrchestrationInboxItem.__table__.create(bind=sqlite_engine)
    session_factory = sessionmaker(bind=sqlite_engine)
    session = session_factory()
    try:
        session.add(Workspace(name="Packet 023 Test", local_path=PROJECT_ROOT))
        session.commit()
    finally:
        session.close()

    secret = "packet-023-secret-value"
    client, original_get_db, engine = make_client(
        session_factory,
        {"discord_router_enabled": True, "discord_ingest_secret": secret},
    )
    try:
        response = client.get("/api/discord-router/status")
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET Discord router status HTTP 200")
        check(payload.get("status") == "success", "GET Discord router status success")
        router_status = payload.get("discord_router") or {}
        check(router_status.get("enabled") is True, "Discord router status enabled")
        check(router_status.get("secret_configured") is True, "Discord router status reports configured secret")
        check(secret not in response.get_data(as_text=True), "Discord router status does not expose secret")

        response = client.post("/api/discord-router/ingest", json={"content": "Missing auth should fail."})
        check(response.status_code == 403, "Discord ingest missing auth HTTP 403")
        check(secret not in response.get_data(as_text=True), "missing auth response does not expose secret")

        response = client.post(
            "/api/discord-router/ingest",
            headers={"X-Nexus-Discord-Secret": "wrong-value"},
            json={"content": "Invalid auth should fail."},
        )
        check(response.status_code == 403, "Discord ingest invalid auth HTTP 403")
        check(secret not in response.get_data(as_text=True), "invalid auth response does not expose secret")

        response = client.post(
            "/api/discord-router/ingest",
            headers={"X-Nexus-Discord-Secret": secret},
            json={
                "content": "Capture this Discord request for triage.",
                "author": {"username": "factory-operator", "id": "123"},
                "channel": {"name": "ops"},
                "timestamp": "2026-05-30T00:00:00Z",
            },
        )
        created = response.get_json(silent=True) or {}
        item = created.get("item") or {}
        check(response.status_code == 201, "Discord ingest valid payload HTTP 201")
        check(created.get("status") == "success", "Discord ingest valid payload success")
        check(item.get("source") == "discord", "Discord ingest creates source discord item")
        check(item.get("status") == "captured", "Discord ingest creates captured item")
        check(item.get("category") == "discord", "Discord ingest creates discord category")
        check("Capture this Discord request" in (item.get("raw_intent") or ""), "Discord ingest stores raw intent")
        check(secret not in response.get_data(as_text=True), "valid ingest response does not expose secret")

        public_settings = engine.public_settings()
        check(public_settings.get("discord_router_enabled") is True, "public settings include Discord enabled flag")
        check(public_settings.get("discord_ingest_secret_configured") is True, "public settings include Discord secret configured flag")
        check("discord_ingest_secret" not in public_settings, "public settings omit Discord ingest secret")
    finally:
        dashboard_module.get_db = original_get_db


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    settings_js = read_file("static/js/settings.js")
    template = read_file("templates/index.html")
    engine = read_file("engine.py")
    preflight = read_file("scripts/nexus_preflight.py")
    service = read_file("src/services/discord_router.py")

    for marker in (
        "/api/discord-router/status",
        "/api/discord-router/ingest",
        "normalize_discord_event",
        "verify_ingest_secret",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in (
        "Discord Event Router",
        "capture_only",
        "input-discord-router-enabled",
        "input-discord-ingest-secret",
    ):
        check(marker in app_js + settings_js + template, "frontend contains {}".format(marker))

    for marker in ("discord_router_enabled", "discord_ingest_secret", "discord_ingest_secret_configured"):
        check(marker in engine, "engine settings contain {}".format(marker))

    check("discord_ingest_secret" in preflight, "preflight raw settings scan includes Discord secret")

    discord_api_section = section_between(dashboard, "/api/discord-router/status", "/api/orchestration-inbox/items")
    discord_ui_section = section_between(app_js, "renderDiscordRouterStatus", "renderFactoryCurrentState")
    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in discord_api_section, "Discord backend avoids {}".format(route))
        check(route not in discord_ui_section, "Discord frontend avoids {}".format(route))

    check("execution_mode" not in discord_api_section, "Discord backend does not set execution mode")
    check("set_execution_mode" not in discord_api_section, "Discord backend does not call set_execution_mode")
    check("alert(" not in discord_ui_section + settings_js, "Discord frontend avoids native alert")
    check("confirm(" not in discord_ui_section + settings_js, "Discord frontend avoids native confirm")
    check("shell" + "=True" not in dashboard + service, "Discord code avoids shell true assignment")
    check("subprocess." + "Popen" not in dashboard + service, "Discord code avoids subprocess popen")

    raw_secret_pattern = re.compile(r"data\.(discord_ingest_secret|gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_secret_pattern.search(app_js + settings_js), "frontend avoids raw secret reads")


def verify_node_check():
    if shutil.which("node") is None:
        print("PASS: node --check skipped because node is unavailable")
        return
    for path in ("static/js/app.js", "static/js/settings.js"):
        result = subprocess.run(
            ["node", "--check", path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
        check(result.returncode == 0, "node --check {}".format(path))


def main():
    verify_docs()
    verify_service()
    verify_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 023 verification failed")
        return 1
    print("PASS: Packet 023 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
