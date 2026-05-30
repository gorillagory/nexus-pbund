import os
import re
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

FAILURES = []


def check(condition, message):
    if condition:
        print("PASS: {}".format(message))
        return
    print("FAIL: {}".format(message))
    FAILURES.append(message)


def read_file(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def verify_service_and_model():
    service_path = os.path.join(PROJECT_ROOT, "src/services/operator_notifications.py")
    check(os.path.exists(service_path), "operator notification service exists")
    service = read_file("src/services/operator_notifications.py")
    models = read_file("models.py")
    schema_sync = read_file("scripts/sync_factory_schema.py")
    preflight = read_file("scripts/nexus_preflight.py")

    check("class OperatorNotification" in models, "OperatorNotification model exists")
    check('__tablename__ = "operator_notifications"' in models, "operator_notifications table exists")
    check('"operator_notifications"' in schema_sync, "schema sync includes operator_notifications")
    check("src/services/operator_notifications.py" in preflight, "preflight compiles operator notification service")

    for name in (
        "build_notification_payload",
        "redact_and_bound_message",
        "should_send_notification",
        "send_discord_notification",
        "record_notification_result",
        "send_test_notification",
        "notification_status",
        "list_recent_notifications",
    ):
        check("def {}(".format(name) in service, "service defines {}".format(name))

    check("request.urlopen" in service, "service sends Discord webhook with urllib")
    check("timeout=5" in service, "Discord webhook send uses timeout")
    check("NEXUS_OPERATOR_NOTIFY_DISCORD_WEBHOOK_URL" in service, "service reads webhook env safely")
    check('"webhook_configured"' in service and '"dashboard_url_configured"' in service, "public notification status uses configured flags")
    check("record_skipped=False" in read_file("dashboard.py"), "integrations do not log disabled notification spam by default")


def verify_routes_and_ui():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    settings_js = read_file("static/js/settings.js")
    template = read_file("templates/index.html")
    engine = read_file("engine.py")

    for route in (
        '/api/operator-notifications/status',
        '/api/operator-notifications/test',
        '/api/operator-notifications/recent',
    ):
        check(route in dashboard and route in template, "{} route exists and is surfaced".format(route))

    check("confirm_send=payload.get(\"confirm_send\") is True" in dashboard, "test route requires confirm_send=true")
    check("sendOperatorTestNotification" in app_js, "dashboard has test notification action")
    check("NexusCore.confirmAction" in app_js, "test notification uses async confirmation pattern")
    check("Mobile Operator Alerts" in template, "dashboard contains Mobile Operator Alerts panel")
    check("operator_notify_discord_webhook_url" in engine, "settings support webhook key")
    check("public.pop(\"operator_notify_discord_webhook_url\", None)" in engine, "public settings remove webhook URL")
    check("public.pop(\"operator_dashboard_url\", None)" in engine, "public settings remove raw dashboard URL")
    check("operator_notify_discord_webhook_configured" in engine, "public settings expose webhook configured flag")
    check("operator_dashboard_url_configured" in engine, "public settings expose dashboard URL configured flag")
    check("input-operator-notify-discord-webhook-url" in template and "input-operator-dashboard-url" in template, "settings UI includes mobile alert fields")
    check("operator_notify_discord_webhook_url" in settings_js, "settings JS saves webhook without displaying existing value")


def verify_integrations():
    dashboard = read_file("dashboard.py")
    for event_type in (
        "packet_run_started",
        "packet_run_completed",
        "packet_run_failed",
        "trusted_packet_blocked",
        "operator_intervention_created",
        "discord_capture_rejected",
        "task_marked_review_required",
    ):
        check(event_type in dashboard, "notification integration exists for {}".format(event_type))

    check("_safe_send_operator_notification" in dashboard, "dashboard uses best-effort notification helper")
    helper = dashboard.split("def _safe_send_operator_notification", 1)[1].split("def _safe_db_commit", 1)[0]
    check("return None" in helper and "except Exception" in helper, "notification failure is best-effort")


def verify_docs_and_env():
    combined_docs = "\n".join(
        read_file(path)
        for path in (
            ".env.example",
            "docs/SPRINT_4_PLAN.md",
            "docs/SPRINT_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
            "docs/OPERATOR_RUNBOOK.md",
            "docs/DEPLOYMENT_RUNBOOK.md",
            "docs/RECOVERY_RUNBOOK.md",
            "docs/PROMPTING_GUIDE.md",
        )
    )
    for phrase in (
        "NEXUS_OPERATOR_NOTIFY_DISCORD_ENABLED",
        "NEXUS_OPERATOR_NOTIFY_DISCORD_WEBHOOK_URL",
        "NEXUS_OPERATOR_DASHBOARD_URL",
        "NEXUS_OPERATOR_NOTIFY_MIN_SEVERITY",
        "NEXUS_OPERATOR_NOTIFY_COOLDOWN_SECONDS",
        "notification-only",
        "Mobile Operator Alerts",
        "Tailscale",
        "no direct Discord execution",
        "Auto-Pilot remains locked",
    ):
        check(phrase in combined_docs, "docs/env mention {}".format(phrase))

    secret_patterns = (
        r"https://discord(?:app)?\.com/api/webhooks/[A-Za-z0-9/_-]{20,}",
        r"sk-[A-Za-z0-9_-]{8,}",
        r"AIza[0-9A-Za-z_-]{20,}",
    )
    for pattern in secret_patterns:
        check(re.search(pattern, combined_docs) is None, "docs/env do not expose raw secret pattern {}".format(pattern))


def verify_safety_static():
    scanned_paths = (
        "src/services/operator_notifications.py",
        "dashboard.py",
        "static/js/app.js",
        "static/js/settings.js",
        "templates/index.html",
    )
    combined = "\n".join(read_file(path) for path in scanned_paths)

    check("shell=True" not in combined, "no shell=True added")
    check("subprocess.Popen" not in combined, "no subprocess.Popen added")
    check("alert(" not in combined, "no native alert added")
    check("confirm(" not in combined, "no native confirm added")

    notification_service = read_file("src/services/operator_notifications.py")
    for forbidden in (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "execution_mode",
        "git push",
        "git reset",
        "git clean",
        "git commit",
        "git merge",
        "git tag",
    ):
        check(forbidden not in notification_service, "notification service does not reference {}".format(forbidden))

    unsafe_claims = (
        "Discord can execute",
        "trusted auto-execution",
        "Auto-Pilot enabled",
    )
    for phrase in unsafe_claims:
        check(phrase not in combined, "UI/code do not claim unsafe behavior: {}".format(phrase))


def verify_service_behavior():
    from src.services.operator_notifications import (
        build_notification_payload,
        notification_status,
        send_test_notification,
    )

    settings = {
        "operator_notify_discord_enabled": True,
        "operator_notify_discord_webhook_url": "https://example.invalid/webhook/example-secret-value-that-must-not-return",
        "operator_dashboard_url": "https://nexus.example.test/dashboard",
        "operator_notify_min_severity": "warning",
        "operator_notify_cooldown_seconds": 30,
    }
    status = notification_status(settings)
    status_text = repr(status)
    check(status["webhook_configured"] is True, "status reports webhook configured")
    check("example-secret-value" not in status_text, "status does not expose webhook URL")
    check("nexus.example.test" not in status_text, "status does not expose raw dashboard URL")

    payload = build_notification_payload(
        settings,
        event_type="packet_run_failed",
        severity="critical",
        title="Failure with token=supersecretvalue",
        summary="Bearer abcdefghijklmnopqrstuvwxyz0123456789 should redact",
    )
    check(len(payload["content"]) <= 1800, "notification payload is bounded")
    check("Bearer abcdefghijklmnopqrstuvwxyz0123456789" not in payload["content"], "notification payload is redacted")
    try:
        send_test_notification(None, 1, settings, confirm_send=False)
        check(False, "send_test_notification rejects missing confirmation")
    except ValueError:
        check(True, "send_test_notification rejects missing confirmation")


def main():
    verify_service_and_model()
    verify_routes_and_ui()
    verify_integrations()
    verify_docs_and_env()
    verify_safety_static()
    verify_service_behavior()
    if FAILURES:
        print("FAIL: Packet 038 verification failed")
        return 1
    print("PASS: Packet 038 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
