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
from models import WorkPacket, Workspace  # noqa: E402
from src.services import trusted_packets  # noqa: E402


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
    WorkPacket.__table__.create(bind=sqlite_engine)
    session_factory = sessionmaker(bind=sqlite_engine)
    session = session_factory()
    try:
        workspace = Workspace(name="Packet 027 Test", local_path=PROJECT_ROOT)
        session.add(workspace)
        session.flush()
        packet = WorkPacket(
            workspace_id=workspace.id,
            title="Packet 027 Test Packet",
            risk_level="medium",
            stop_condition="Stop after verification.",
            estimated_minutes="10",
            status="staged",
        )
        session.add(packet)
        session.commit()
    finally:
        session.close()
    return session_factory


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


def first_packet_id(session_factory):
    session = session_factory()
    try:
        return session.query(WorkPacket).first().id
    finally:
        session.close()


def verify_docs():
    required = {
        "docs/WORKFLOW_LOCK.md": [
            "Trusted Packet Mode",
            "trust_status=trusted",
            "does not unlock Auto-Pilot",
        ],
        "docs/SPRINT_PLAN.md": [
            "Packet 027 Trusted Packet Mode foundation",
            "Trusted Packet Mode rule",
            "supervised packet execution is restricted",
        ],
        "docs/CHAT_HANDOFF.md": [
            "Trusted Packet Mode",
            "Packet 027",
            "nexus-trusted-packet-mode-baseline-2026-05-30",
        ],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_model():
    columns = set(WorkPacket.__table__.columns.keys())
    expected_columns = {
        "trust_status",
        "trust_level",
        "trust_reason",
        "trust_reviewer",
        "trust_notes",
        "trusted_at",
        "revoked_at",
    }
    check(expected_columns.issubset(columns), "work packet model has additive trust metadata")


def verify_service():
    check(trusted_packets.TRUST_STATUSES == {"unreviewed", "trusted", "revoked"}, "trust statuses are constrained")
    check(trusted_packets.TRUST_LEVELS == {"standard", "elevated"}, "trust levels are constrained")

    session_factory = make_session_factory()
    session = session_factory()
    try:
        packet = session.query(WorkPacket).first()
        gate = trusted_packets.packet_trust_eligible(packet, trusted_packet_mode_enabled=False)
        check(gate.get("eligible") is True, "disabled trust gate allows unreviewed packet")
        gate = trusted_packets.packet_trust_eligible(packet, trusted_packet_mode_enabled=True)
        check(gate.get("eligible") is False, "enabled trust gate blocks unreviewed packet")

        no_confirm_failed = False
        try:
            trusted_packets.mark_packet_trusted(session, packet, {"trust_reason": "reviewed"})
        except ValueError:
            no_confirm_failed = True
        check(no_confirm_failed, "mark trusted requires explicit confirmation")

        no_reason_failed = False
        try:
            trusted_packets.mark_packet_trusted(session, packet, {"confirm_trust": True})
        except ValueError:
            no_reason_failed = True
        check(no_reason_failed, "mark trusted requires reason or notes")

        fake_secret = "sk-" + "packet027secret"
        packet = trusted_packets.mark_packet_trusted(
            session,
            packet,
            {
                "confirm_trust": True,
                "trust_level": "elevated",
                "trust_reason": "Reviewed with token={}".format(fake_secret),
                "trust_reviewer": "operator",
                "trust_notes": "password=packet027secret",
            },
        )
        serialized = trusted_packets.serialize_trust_metadata(packet)
        check(packet.trust_status == "trusted", "mark trusted sets status")
        check(packet.trust_level == "elevated", "mark trusted sets level")
        check(fake_secret not in (packet.trust_reason or ""), "service redacts trust reason")
        check("packet027secret" not in str(serialized), "service redacts serialized trust metadata")
        gate = trusted_packets.packet_trust_eligible(packet, trusted_packet_mode_enabled=True)
        check(gate.get("eligible") is True, "enabled trust gate allows trusted packet")

        revoke_failed = False
        try:
            trusted_packets.revoke_packet_trust(session, packet, {"reason": "review changed"})
        except ValueError:
            revoke_failed = True
        check(revoke_failed, "revoke trust requires explicit confirmation")

        packet = trusted_packets.revoke_packet_trust(
            session,
            packet,
            {"confirm_revoke": True, "reason": "Review changed."},
        )
        check(packet.trust_status == "revoked", "revoke trust sets revoked status")
        check(packet.revoked_at is not None, "revoke trust records revoked_at")
    finally:
        session.close()


def verify_routes():
    session_factory = make_session_factory()
    packet_id = first_packet_id(session_factory)
    client, original_get_db, engine = make_client(
        session_factory,
        {"trusted_packet_mode_enabled": True, "execution_mode": "one_packet"},
    )
    try:
        public_settings = engine.public_settings()
        check(public_settings.get("trusted_packet_mode_enabled") is True, "public settings expose trusted packet mode flag")

        response = client.get("/api/trusted-packets/status?work_packet_id={}".format(packet_id))
        payload = response.get_json(silent=True) or {}
        trusted_status = payload.get("trusted_packets") or {}
        check(response.status_code == 200, "trusted packet status route HTTP 200")
        check(payload.get("status") == "success", "trusted packet status route success")
        check(trusted_status.get("trusted_packet_mode_enabled") is True, "trusted packet status reports enabled mode")
        check((trusted_status.get("packet") or {}).get("eligible") is False, "trusted packet status reports blocked unreviewed packet")

        response = client.post(
            "/api/work-packets/{}/trust".format(packet_id),
            json={"trust_reason": "Reviewed by operator."},
        )
        check(response.status_code == 400, "trust route without confirmation HTTP 400")

        response = client.post(
            "/api/work-packets/{}/trust".format(packet_id),
            json={"confirm_trust": True},
        )
        check(response.status_code == 400, "trust route without reason HTTP 400")

        fake_secret = "sk-" + "packet027route"
        response = client.post(
            "/api/work-packets/{}/trust".format(packet_id),
            json={
                "confirm_trust": True,
                "trust_level": "standard",
                "trust_reason": "Reviewed with token={}".format(fake_secret),
                "trust_reviewer": "operator",
            },
        )
        payload = response.get_json(silent=True) or {}
        trust = payload.get("trust") or {}
        check(response.status_code == 200, "trust route HTTP 200")
        check(trust.get("trust_status") == "trusted", "trust route marks packet trusted")
        check(fake_secret not in response.get_data(as_text=True), "trust route redacts secret-looking text")

        response = client.post(
            "/api/work-packets/{}/revoke-trust".format(packet_id),
            json={"reason": "Review changed."},
        )
        check(response.status_code == 400, "revoke route without confirmation HTTP 400")

        response = client.post(
            "/api/work-packets/{}/revoke-trust".format(packet_id),
            json={"confirm_revoke": True, "reason": "Review changed."},
        )
        payload = response.get_json(silent=True) or {}
        trust = payload.get("trust") or {}
        check(response.status_code == 200, "revoke route HTTP 200")
        check(trust.get("trust_status") == "revoked", "revoke route marks packet revoked")

        response = client.post(
            "/api/work-packets/run",
            json={"workspace_id": 1, "work_packet_id": packet_id},
        )
        payload = response.get_json(silent=True) or {}
        gate = payload.get("trusted_packet_gate") or {}
        check(response.status_code == 403, "trusted packet execution gate rejects revoked packet")
        check(payload.get("status") == "error", "trusted packet execution gate returns error")
        check(gate.get("eligible") is False, "trusted packet execution gate is restrictive")
    finally:
        dashboard_module.get_db = original_get_db


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    settings_js = read_file("static/js/settings.js")
    template = read_file("templates/index.html")
    styles = read_file("static/style.css")
    models = read_file("models.py")
    engine = read_file("engine.py")
    preflight = read_file("scripts/nexus_preflight.py")
    schema_sync = read_file("scripts/sync_factory_schema.py")
    service = read_file("src/services/trusted_packets.py")

    for marker in (
        "trust_status",
        "trust_level",
        "trusted_at",
        "revoked_at",
    ):
        check(marker in models, "models.py contains {}".format(marker))

    for marker in (
        "/api/trusted-packets/status",
        "/api/work-packets/<int:work_packet_id>/trust",
        "/api/work-packets/<int:work_packet_id>/revoke-trust",
        "packet_trust_eligible",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in (
        "Trusted Packet Mode",
        "trusted-packet-status",
        "trustSelectedWorkPacket",
        "revokeSelectedWorkPacketTrust",
        "NexusCore.confirmAction",
    ):
        check(marker in app_js + template, "frontend contains {}".format(marker))

    check("trusted_packet_mode_enabled" in engine + settings_js + template, "settings contain trusted packet mode flag")
    check("src/services/trusted_packets.py" in preflight, "preflight py_compile includes trusted packet service")
    check("trust_status" in schema_sync, "schema sync includes trust metadata")
    check("redact_git_output" in service, "trusted packet service uses redaction")
    check("TRUST_STATUSES" in service and "TRUST_LEVELS" in service, "trusted packet service declares constrained values")
    check("subprocess.run" not in service, "trusted packet service does not run subprocess commands")
    check("shell" + "=True" not in service + dashboard, "trusted packet code avoids shell true assignment")
    check("subprocess." + "Popen" not in service + dashboard, "trusted packet code avoids subprocess popen")

    route_section = section_between(dashboard, "/api/trusted-packets/status", "/api/work-packets/run")
    app_section = section_between(app_js, "loadTrustedPacketStatus", "renderWorkPacketPreview")
    settings_section = section_between(settings_js, "input-trusted-packet-mode-enabled", "refreshModelPreview")

    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in route_section, "trusted packet routes avoid {}".format(route))
        check(route not in app_section, "trusted packet frontend avoids direct {}".format(route))

    blocked_terms = (
        "set_execution_mode",
        "execution_mode = \"autopilot\"",
        "retry_one_task",
        "continue_work_packet",
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
    lowered = (route_section + app_section + service + settings_section).lower()
    for term in blocked_terms:
        check(term not in lowered, "trusted packet implementation avoids {}".format(term))

    run_gate_section = section_between(dashboard, "packet_trust_eligible(", "packet_links =")
    check("return jsonify" in run_gate_section and "), 403" in run_gate_section, "execution gate only rejects untrusted packets")
    check("Trusted Packet Mode requires trust_status=trusted" in run_gate_section, "execution gate has clear safe error")

    ui_section = section_between(app_js + template, "Trusted Packet Mode", "Preview extracted tasks")
    check("alert(" not in app_section + settings_js, "trusted packet frontend avoids native alert")
    check("confirm(" not in app_section + settings_js, "trusted packet frontend avoids native confirm")
    check("trusted-packet-panel" in styles, "stylesheet contains trusted packet surface styles")

    button_text = " ".join(re.findall(r"<button\b[^>]*>(.*?)</button>", ui_section, flags=re.DOTALL | re.IGNORECASE))
    button_text = re.sub(r"<[^>]+>", " ", button_text)
    for label in ("Run Codex", "Retry", "Continue", "Switch", "Commit", "Merge", "Push", "Reset", "Clean", "Tag"):
        check(label.lower() not in button_text.lower(), "trusted packet UI has no {} button".format(label))


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
    verify_model()
    verify_service()
    verify_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 027 verification failed")
        return 1
    print("PASS: Packet 027 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
