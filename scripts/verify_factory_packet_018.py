import os
import re
import shutil
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import engine as engine_module  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from engine import NexusEngine  # noqa: E402
from src.services.ci_status import summarize_ci_status  # noqa: E402


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


def run_command(command):
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def verify_service_summary():
    summary = summarize_ci_status(PROJECT_ROOT)
    check(isinstance(summary, dict), "summarize_ci_status returns dict")
    for key in (
        "branch",
        "commit",
        "workflow_present",
        "workflow_path",
        "actions_url",
        "local_preflight",
        "remote_ci",
    ):
        check(key in summary, "ci summary has {}".format(key))
    check((summary.get("remote_ci") or {}).get("status") == "unknown", "remote CI status is unknown")
    check(
        (summary.get("remote_ci") or {}).get("reason") == "GitHub API integration not configured",
        "remote CI reason explains no GitHub API",
    )
    check(summary.get("workflow_path") == ".github/workflows/nexus-preflight.yml", "workflow path is stable")


def verify_flask_route():
    original_chat_store = engine_module.ChatSessionStore
    engine_module.ChatSessionStore = NoopChatSessionStore
    try:
        engine = NexusEngine(PROJECT_ROOT)
        dashboard = NexusDashboard(engine)
        dashboard.app.config["TESTING"] = True
        response = dashboard.app.test_client().get("/api/factory/ci-status")
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "GET /api/factory/ci-status HTTP 200")
        check(payload.get("status") == "success", "GET /api/factory/ci-status success")
        check(isinstance(payload.get("ci"), dict), "GET /api/factory/ci-status returns ci dict")
    finally:
        engine_module.ChatSessionStore = original_chat_store


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    service = read_file("src/services/ci_status.py")
    ci_js_section = section_between(app_js, "async loadFactoryCiStatus()", "renderFactoryPreflightStatus")

    check("/api/factory/ci-status" in dashboard, "dashboard has CI status route")
    check("CI / Preflight Status" in app_js + template, "UI contains CI / Preflight Status")
    check("/api/factory/ci-status" in app_js, "frontend calls CI status route")
    check("subprocess.run" in service, "ci_status service uses subprocess.run")
    check("shell" + "=True" not in service + dashboard, "no shell true assignment in CI status code")
    check("subprocess." + "Popen" not in service + dashboard, "no subprocess popen in CI status code")
    check("requests." not in service and "urllib" not in service, "ci_status service has no network client")
    check("github.com" in service, "ci_status service can build GitHub Actions URL")

    forbidden = [
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    ]
    for fragment in forbidden:
        check(fragment not in ci_js_section, "CI frontend avoids {}".format(fragment))
        check(fragment not in service, "CI service avoids {}".format(fragment))

    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_key_pattern.search(app_js), "frontend has no raw API key reads")


def verify_node_check():
    if shutil.which("node") is None:
        print("PASS: node --check skipped because node is unavailable")
        return
    result = run_command(["node", "--check", "static/js/app.js"])
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    check(result.returncode == 0, "node --check static/js/app.js")


def main():
    verify_service_summary()
    verify_flask_route()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 018 verification failed")
        return 1
    print("PASS: Packet 018 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
