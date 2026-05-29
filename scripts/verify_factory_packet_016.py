import os
import re
import sys
import types


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import dashboard as dashboard_module  # noqa: E402
import engine as engine_module  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from engine import NexusEngine  # noqa: E402


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


def verify_source():
    dashboard = read_file("dashboard.py")
    template = read_file("templates/index.html")
    app_js = read_file("static/js/app.js")
    ui_text = template + "\n" + app_js
    preflight_section = section_between(
        dashboard,
        '"/api/factory/preflight/status"',
        '"/api/factory/events/manual"',
    )
    js_preflight_section = section_between(
        app_js,
        "async loadFactoryPreflightStatus()",
        "async loadFactoryEvents()",
    )

    check("/api/factory/preflight/status" in dashboard, "dashboard has preflight status route")
    check("/api/factory/preflight/run" in dashboard, "dashboard has preflight run route")
    check("scripts/nexus_preflight.py" in dashboard, "dashboard references nexus_preflight.py")
    check("subprocess.run" in dashboard, "dashboard uses subprocess.run")
    check("timeout=" in dashboard, "preflight runner uses timeout")
    check("shell" + "=True" not in preflight_section, "preflight route avoids shell true assignment")
    check("subprocess." + "Popen" not in preflight_section, "preflight route avoids subprocess popen")

    check("Preflight / CI Status" in ui_text, "UI contains Preflight / CI Status")
    check("/api/factory/preflight/status" in app_js, "frontend calls preflight status route")
    check("/api/factory/preflight/run" in app_js, "frontend calls preflight run route")
    check("Run Local Quick Preflight" in ui_text, "UI contains run local quick preflight button")

    forbidden = [
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    ]
    for fragment in forbidden:
        check(fragment not in preflight_section, "preflight backend avoids {}".format(fragment))
        check(fragment not in js_preflight_section, "preflight frontend avoids {}".format(fragment))


def verify_flask_routes():
    original_chat_store = engine_module.ChatSessionStore
    original_run = dashboard_module.subprocess.run
    engine_module.ChatSessionStore = NoopChatSessionStore
    try:
        engine = NexusEngine(PROJECT_ROOT)
        dashboard = NexusDashboard(engine)
        dashboard.app.config["TESTING"] = True
        client = dashboard.app.test_client()

        status_response = client.get("/api/factory/preflight/status")
        status_payload = status_response.get_json(silent=True) or {}
        preflight = status_payload.get("preflight") or {}
        check(status_response.status_code == 200, "GET preflight status returns HTTP 200")
        check(status_payload.get("status") == "success", "GET preflight status returns success")
        check("workflow_present" in preflight, "preflight status has workflow_present")
        check("quick_command" in preflight, "preflight status has quick_command")

        calls = []

        def fake_run(command, **kwargs):
            calls.append({"command": command, "kwargs": kwargs})
            return types.SimpleNamespace(
                returncode=0,
                stdout="NEXUS_PREFLIGHT_RESULT=PASS\n",
                stderr="",
            )

        dashboard_module.subprocess.run = fake_run
        run_response = client.post("/api/factory/preflight/run")
        run_payload = run_response.get_json(silent=True) or {}
        check(run_response.status_code == 200, "POST preflight run returns HTTP 200")
        check(run_payload.get("status") == "success", "POST preflight run returns success")
        check((run_payload.get("result") or {}).get("result") == "pass", "POST preflight run records pass")
        check(len(calls) == 1, "POST preflight run uses mocked subprocess once")
        check(
            calls and calls[0]["command"] == ["python3", "scripts/nexus_preflight.py", "--quick"],
            "POST preflight run uses quick preflight command",
        )
        check(calls and calls[0]["kwargs"].get("shell") is None, "POST preflight run does not set shell")
        check(calls and calls[0]["kwargs"].get("timeout") == 300, "POST preflight run uses 300 second timeout")
    finally:
        dashboard_module.subprocess.run = original_run
        engine_module.ChatSessionStore = original_chat_store


def verify_safety():
    dashboard = read_file("dashboard.py")
    engine = read_file("engine.py")
    app_js = read_file("static/js/app.js")
    preflight_section = section_between(
        dashboard,
        '"/api/factory/preflight/status"',
        '"/api/factory/events/manual"',
    )
    js_preflight_section = section_between(
        app_js,
        "async loadFactoryPreflightStatus()",
        "async loadFactoryEvents()",
    )

    check("shell" + "=True" not in dashboard + engine, "no shell true assignment in dashboard.py or engine.py")
    check("subprocess." + "Popen" not in dashboard, "no subprocess popen in dashboard.py")
    check("return self.engine.settings" not in dashboard + engine, "no raw settings return")
    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_key_pattern.search(app_js), "no frontend raw API key reads")
    check("codex exec" not in preflight_section.lower(), "preflight backend does not run Codex")
    check("autopilot" not in preflight_section.lower(), "preflight backend does not start Auto-Pilot")
    check("autopilot" not in js_preflight_section.lower(), "preflight frontend does not start Auto-Pilot")


def main():
    verify_source()
    verify_flask_routes()
    verify_safety()
    if FAILURES:
        print("FAIL: Packet 016 verification failed")
        return 1
    print("PASS: Packet 016 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
