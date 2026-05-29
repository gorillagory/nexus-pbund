import os
import re
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def fail(message):
    print("FAIL: {}".format(message))
    return False


def pass_line(message):
    print("PASS: {}".format(message))


def read_text(relative_path):
    path = os.path.join(ROOT_DIR, relative_path)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def js_method_body(source, method_name):
    match = re.search(
        r"(?:async\s+)?{}\s*\([^)]*\)\s*\{{(?P<body>.*?)(?=\n    (?:async\s+)?[A-Za-z0-9_]+\s*\([^)]*\)\s*\{{|\n\}};)".format(
            re.escape(method_name)
        ),
        source,
        re.DOTALL,
    )
    return match.group("body") if match else ""


def factory_console_source(app_text, template_text):
    methods = (
        "loadFactoryConsole",
        "renderFactoryConsole",
        "loadFactoryEvents",
        "loadFactoryRuns",
        "loadFactoryGitStatus",
        "submitManualFactoryEvent",
    )
    method_source = "\n".join(js_method_body(app_text, method) for method in methods)
    marker = "Factory Run Console"
    index = template_text.find(marker)
    template_source = template_text[index:] if index != -1 else ""
    return method_source + "\n" + template_source


def response_is_json(response):
    try:
        data = response.get_json()
    except Exception:
        data = None
    return isinstance(data, dict), data or {}


def main():
    checks = []

    from models import (  # noqa: F401
        ExecutionChangedFile,
        ExecutionRun,
        FactoryEvent,
        WorkPacket,
        WorkPacketTask,
    )

    checks.extend(
        [
            WorkPacket is not None,
            WorkPacketTask is not None,
            ExecutionRun is not None,
            ExecutionChangedFile is not None,
            FactoryEvent is not None,
        ]
    )
    pass_line("factory execution models import")

    from src.services import factory_events, git_changes

    required_factory_helpers = (
        "serialize_factory_event",
        "serialize_execution_run",
        "serialize_changed_file",
        "create_factory_event",
        "get_recent_factory_events",
        "get_recent_execution_runs",
        "summarize_factory_state",
    )
    required_git_helpers = (
        "run_git_command",
        "get_git_status",
        "get_git_diff_stat",
        "get_changed_files",
        "summarize_git_changes",
    )
    for helper in required_factory_helpers:
        checks.append(hasattr(factory_events, helper) or fail("factory_events missing {}".format(helper)))
    for helper in required_git_helpers:
        checks.append(hasattr(git_changes, helper) or fail("git_changes missing {}".format(helper)))
    pass_line("factory event and git service helpers import")

    before = git_changes.summarize_git_changes(ROOT_DIR)
    after = git_changes.summarize_git_changes(ROOT_DIR)
    checks.append(isinstance(before, dict) or fail("summarize_git_changes did not return dict"))
    checks.append("changed_files" in before or fail("git summary missing changed_files"))
    checks.append("is_dirty" in before or fail("git summary missing is_dirty"))
    checks.append(
        before.get("status_output") == after.get("status_output")
        or fail("git summary appears to mutate status output")
    )
    pass_line("git changes service summarizes without mutation")

    dashboard_text = read_text("dashboard.py")
    for route in (
        "/api/factory/status",
        "/api/factory/events",
        "/api/factory/runs",
        "/api/factory/git-status",
        "/api/factory/events/manual",
    ):
        checks.append(route in dashboard_text or fail("dashboard route missing {}".format(route)))
    pass_line("factory dashboard routes are present")

    app_text = read_text("static/js/app.js")
    template_text = read_text("templates/index.html")
    ui_text = app_text + "\n" + template_text
    checks.append("Factory Run Console" in ui_text or fail("Factory Run Console UI missing"))
    checks.append('"/api/factory/status"' in app_text or fail("frontend factory status endpoint missing"))
    checks.append('"/api/factory/git-status"' in app_text or fail("frontend factory git endpoint missing"))
    checks.append(
        '"/api/factory/events/manual"' in app_text
        or fail("frontend manual factory event endpoint missing")
    )
    console_source = factory_console_source(app_text, template_text)
    checks.append(console_source.strip() or fail("factory console source section not found"))
    checks.append(
        "/api/execute-codex" not in console_source
        or fail("Factory Run Console calls /api/execute-codex")
    )
    checks.append(
        "/api/tasks/auto-run" not in console_source
        or fail("Factory Run Console calls /api/tasks/auto-run")
    )
    pass_line("Factory Run Console frontend is present and non-executing")

    safety_files = [
        "dashboard.py",
        "engine.py",
        "src/services/factory_events.py",
        "src/services/git_changes.py",
    ]
    safety_text = "\n".join(read_text(path) for path in safety_files)
    checks.append("shell=True" not in safety_text or fail("shell=True introduced"))
    checks.append("subprocess.Popen" not in safety_text or fail("subprocess.Popen introduced"))
    frontend_secret_read = re.search(
        r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)",
        app_text,
    )
    checks.append(frontend_secret_read is None or fail("raw API key frontend read found"))
    pass_line("source safety checks pass")

    import engine as engine_module
    from dashboard import NexusDashboard
    from engine import NexusEngine

    class DummyChatSessionStore:
        def __init__(self, max_messages=20):
            self.max_messages = max_messages

    engine_module.ChatSessionStore = DummyChatSessionStore
    engine = NexusEngine(ROOT_DIR)
    dashboard = NexusDashboard(engine)
    client = dashboard.app.test_client()
    for route in (
        "/api/factory/status",
        "/api/factory/events",
        "/api/factory/runs",
        "/api/factory/git-status",
    ):
        response = client.get(route)
        is_json, data = response_is_json(response)
        print("PASS: {} returned HTTP {}".format(route, response.status_code))
        checks.append(is_json or fail("{} did not return JSON".format(route)))
        if route == "/api/factory/git-status":
            checks.append(response.status_code == 200 or fail("git-status route should not depend on DB"))
            checks.append(data.get("status") == "success" or fail("git-status route status is not success"))
        else:
            checks.append(
                response.status_code == 200
                or (response.status_code >= 400 and data.get("status") == "error")
                or fail("{} did not return success or clear JSON error".format(route))
            )
    pass_line("factory API routes respond through Flask test client")

    if not all(checks):
        return 1

    pass_line("Factory execution console verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
