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
from models import OperatorIntervention, Workspace  # noqa: E402
from src.services import operator_interventions  # noqa: E402


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


def make_session_factory():
    sqlite_engine = create_engine("sqlite:///:memory:")
    Workspace.__table__.create(bind=sqlite_engine)
    OperatorIntervention.__table__.create(bind=sqlite_engine)
    session_factory = sessionmaker(bind=sqlite_engine)
    session = session_factory()
    try:
        session.add(Workspace(name="Packet 026 Test", local_path=PROJECT_ROOT))
        session.commit()
    finally:
        session.close()
    return session_factory


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


def verify_docs():
    required = {
        "docs/WORKFLOW_LOCK.md": [
            "Operator Intervention Queue",
            "does not execute tasks",
            "Recovery controls remain separate",
        ],
        "docs/SPRINT_PLAN.md": [
            "Packet 026 Operator Intervention Queue foundation",
            "Operator Intervention Queue rule",
            "must not execute tasks",
        ],
        "docs/CHAT_HANDOFF.md": [
            "Operator Intervention Queue",
            "Packet 026",
            "Packet 027",
        ],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_model():
    columns = set(OperatorIntervention.__table__.columns.keys())
    expected_columns = {
        "id",
        "workspace_id",
        "title",
        "details",
        "source_type",
        "source_id",
        "severity",
        "status",
        "category",
        "recommended_action",
        "operator_notes",
        "context_json",
        "created_at",
        "updated_at",
        "acknowledged_at",
        "resolved_at",
    }
    check(expected_columns.issubset(columns), "operator intervention model has required fields")
    check(OperatorIntervention.__tablename__ == "operator_interventions", "operator intervention table name is set")


def verify_service():
    check(
        operator_interventions.INTERVENTION_STATUSES == {"open", "acknowledged", "resolved", "dismissed"},
        "intervention statuses are constrained",
    )
    check(
        operator_interventions.INTERVENTION_SEVERITIES == {"info", "warning", "blocked", "critical"},
        "intervention severities are constrained",
    )

    session_factory = make_session_factory()
    session = session_factory()
    try:
        workspace = session.query(Workspace).filter(Workspace.local_path == PROJECT_ROOT).one()
        fake_secret = "sk-" + "packet026secret"
        item = operator_interventions.create_intervention(
            session,
            workspace.id,
            {
                "title": "Needs operator review",
                "details": "Review blocker with token={}".format(fake_secret),
                "severity": "critical",
                "category": "review",
                "recommended_action": "Decide next safe packet step.",
                "operator_notes": "password=packet026secret",
                "context": {"authorization": "Bearer {}".format(fake_secret)},
            },
        )
        serialized = operator_interventions.serialize_intervention(item)
        check(item.status == "open", "created intervention defaults to open")
        check(item.severity == "critical", "created intervention stores valid severity")
        check(fake_secret not in item.details, "service redacts secrets before storing details")
        check("packet026secret" not in str(serialized), "service redacts secrets before returning serialized item")

        listed = operator_interventions.list_interventions(session, workspace.id, status="open", severity="critical")
        check(len(listed) == 1 and listed[0].id == item.id, "service lists filtered interventions")

        item = operator_interventions.update_intervention(
            session,
            item,
            {"operator_notes": "Reviewed without exposing token={}".format(fake_secret), "severity": "blocked"},
        )
        check(item.severity == "blocked", "service updates constrained severity")
        check(fake_secret not in (item.operator_notes or ""), "service redacts updated notes")

        item = operator_interventions.acknowledge_intervention(session, item, operator_notes="ack")
        check(item.status == "acknowledged" and item.acknowledged_at is not None, "service acknowledges item")
        item = operator_interventions.resolve_intervention(session, item, operator_notes="resolved")
        check(item.status == "resolved" and item.resolved_at is not None, "service resolves item")
        item = operator_interventions.dismiss_intervention(session, item, operator_notes="dismissed")
        check(item.status == "dismissed", "service dismisses item")
    finally:
        session.close()


def verify_routes():
    session_factory = make_session_factory()
    client, original_get_db = make_client(session_factory)
    try:
        response = client.get("/api/operator-interventions")
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET intervention queue HTTP 200")
        check(payload.get("status") == "success", "GET intervention queue success")
        check(payload.get("items") == [], "GET intervention queue starts empty")

        fake_secret = "sk-" + "packet026route"
        response = client.post(
            "/api/operator-interventions",
            json={
                "title": "Route-created review",
                "details": "Operator should review token={}".format(fake_secret),
                "severity": "warning",
                "category": "manual",
                "recommended_action": "Record decision only.",
            },
        )
        payload = response.get_json(silent=True) or {}
        item = payload.get("item") or {}
        item_id = item.get("id")
        check(response.status_code == 201, "POST intervention queue HTTP 201")
        check(payload.get("status") == "success", "POST intervention queue success")
        check(item.get("status") == "open", "POST creates open intervention")
        check(item.get("severity") == "warning", "POST creates warning severity")
        check(fake_secret not in response.get_data(as_text=True), "POST response redacts secret-looking text")

        response = client.patch(
            "/api/operator-interventions/{}".format(item_id),
            json={"operator_notes": "Human review recorded.", "severity": "blocked"},
        )
        payload = response.get_json(silent=True) or {}
        item = payload.get("item") or {}
        check(response.status_code == 200, "PATCH intervention queue HTTP 200")
        check(item.get("severity") == "blocked", "PATCH updates queue fields")
        check(item.get("operator_notes") == "Human review recorded.", "PATCH updates operator notes")

        response = client.post(
            "/api/operator-interventions/{}/acknowledge".format(item_id),
            json={"operator_notes": "Acknowledged by operator."},
        )
        item = (response.get_json(silent=True) or {}).get("item") or {}
        check(response.status_code == 200, "acknowledge route HTTP 200")
        check(item.get("status") == "acknowledged", "acknowledge route updates status only")

        response = client.post(
            "/api/operator-interventions/{}/resolve".format(item_id),
            json={"operator_notes": "Resolved by operator."},
        )
        item = (response.get_json(silent=True) or {}).get("item") or {}
        check(response.status_code == 200, "resolve route HTTP 200")
        check(item.get("status") == "resolved", "resolve route updates status only")

        response = client.post(
            "/api/operator-interventions",
            json={"title": "Dismiss test", "details": "Record a dismissed item."},
        )
        second_id = ((response.get_json(silent=True) or {}).get("item") or {}).get("id")
        response = client.post(
            "/api/operator-interventions/{}/dismiss".format(second_id),
            json={"operator_notes": "Dismissed by operator."},
        )
        item = (response.get_json(silent=True) or {}).get("item") or {}
        check(response.status_code == 200, "dismiss route HTTP 200")
        check(item.get("status") == "dismissed", "dismiss route updates status only")
    finally:
        dashboard_module.get_db = original_get_db


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    styles = read_file("static/style.css")
    models = read_file("models.py")
    preflight = read_file("scripts/nexus_preflight.py")
    schema_sync = read_file("scripts/sync_factory_schema.py")
    service = read_file("src/services/operator_interventions.py")

    for marker in (
        "class OperatorIntervention",
        "__tablename__ = \"operator_interventions\"",
    ):
        check(marker in models, "models.py contains {}".format(marker))

    for marker in (
        "/api/operator-interventions",
        "/api/operator-interventions/<int:intervention_id>/acknowledge",
        "/api/operator-interventions/<int:intervention_id>/resolve",
        "/api/operator-interventions/<int:intervention_id>/dismiss",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in (
        "Operator Intervention Queue",
        "operator-intervention-list",
        "createOperatorIntervention",
        "changeSelectedOperatorInterventionStatus",
        "NexusCore.confirmAction",
    ):
        check(marker in app_js + template, "frontend contains {}".format(marker))

    check("src/services/operator_interventions.py" in preflight, "preflight py_compile includes intervention service")
    check("operator_interventions" in schema_sync, "schema sync includes intervention table")
    check("redact_git_output" in service, "service uses redaction helper")
    check("INTERVENTION_STATUSES" in service and "INTERVENTION_SEVERITIES" in service, "service declares constrained values")
    check("subprocess.run" not in service, "intervention service does not run subprocess commands")
    check("shell" + "=True" not in service + dashboard, "intervention code avoids shell true assignment")
    check("subprocess." + "Popen" not in service + dashboard, "intervention code avoids subprocess popen")

    route_section = section_between(dashboard, "/api/operator-interventions", "/api/prompt-vault/templates")
    app_section = section_between(app_js, "loadOperatorInterventions", "loadPromptVaultTemplates")
    ui_section = section_between(template, "view-operator-interventions", "view-prompt-vault")

    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in route_section, "intervention routes avoid {}".format(route))
        check(route not in app_section, "intervention frontend avoids {}".format(route))

    blocked_terms = (
        "retry",
        "continue_packet",
        "set_execution_mode",
        "execution_mode",
        "prepare_packet_branch",
        "git switch",
        "git add",
        "git commit",
        "git merge",
        "git push",
        "git reset",
        "git clean",
        "git tag",
    )
    lowered_route_section = route_section.lower()
    for term in blocked_terms:
        check(term not in lowered_route_section, "intervention routes avoid {}".format(term))

    button_text = " ".join(re.findall(r"<button\b[^>]*>(.*?)</button>", ui_section, flags=re.DOTALL | re.IGNORECASE))
    button_text = re.sub(r"<[^>]+>", " ", button_text)
    for label in ("Run", "Retry", "Continue", "Codex", "Switch", "Commit", "Merge", "Push", "Reset", "Clean", "Tag"):
        check(label.lower() not in button_text.lower(), "intervention UI has no {} button".format(label))

    check("alert(" not in app_section, "intervention frontend avoids native alert")
    check("confirm(" not in app_section, "intervention frontend avoids native confirm")
    check("operator-intervention-panel" in styles, "stylesheet contains intervention surface styles")


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
    verify_model()
    verify_service()
    verify_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 026 verification failed")
        return 1
    print("PASS: Packet 026 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
