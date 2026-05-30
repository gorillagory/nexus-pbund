import ast
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


def route_section(source, marker, next_marker="@self.app.route"):
    start = source.find(marker)
    if start < 0:
        return ""
    next_start = source.find(next_marker, start + len(marker))
    return source[start:] if next_start < 0 else source[start:next_start]


def parse_python(relative_path):
    return ast.parse(read_file(relative_path), filename=relative_path)


def iter_python_files(relative_roots):
    for relative_root in relative_roots:
        full_root = os.path.join(PROJECT_ROOT, relative_root)
        if os.path.isfile(full_root):
            yield relative_root
            continue
        for root, dirs, files in os.walk(full_root):
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            ]
            for file_name in files:
                if file_name.endswith(".py"):
                    yield os.path.relpath(os.path.join(root, file_name), PROJECT_ROOT)


def has_shell_true(relative_path):
    tree = parse_python(relative_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return True
    return False


def has_popen(relative_path):
    tree = parse_python(relative_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "Popen":
            return True
        if isinstance(func, ast.Name) and func.id == "Popen":
            return True
    return False


def verify_service():
    service_path = "src/services/simple_operator_flow.py"
    check(os.path.exists(os.path.join(PROJECT_ROOT, service_path)), "simple operator service exists")
    service = read_file(service_path)

    for phrase in (
        "SIMPLE_SOURCE = \"simple_operator\"",
        "def create_simple_request",
        "def generate_simple_draft",
        "def update_simple_draft",
        "def prepare_simple_work_packet",
        "def evaluate_simple_readiness",
        "def serialize_simple_flow",
        "def simple_run_blockers",
        "MAX_SNIPPET_CHARS",
        "redact_git_output",
        "report_path",
        "PacketPromptDraft",
        "WorkPacket",
        "WorkPacketTask",
        "ExecutionRun",
        "packet_trust_eligible",
        "trust_status=\"unreviewed\"",
    ):
        check(phrase in service, "service contains {}".format(phrase))

    for confirmation in ("confirm_create", "confirm_generate", "confirm_prepare", "confirm_evaluate"):
        check(confirmation in service, "service requires {}".format(confirmation))

    forbidden = (
        "mark_packet_trusted",
        "revoke_packet_trust",
        "/api/tasks/auto-run",
        "auto_run_tasks",
        "set_execution_mode",
        "git push",
        "git reset",
        "git clean",
        "shell=True",
        "subprocess.Popen",
    )
    for phrase in forbidden:
        check(phrase not in service, "service avoids {}".format(phrase))


def verify_routes():
    dashboard = read_file("dashboard.py")
    for route in (
        "/api/simple-operator/status",
        "/api/simple-operator/request",
        "/api/simple-operator/<int:flow_id>/draft",
        "/api/simple-operator/<int:flow_id>/prepare-work-packet",
        "/api/simple-operator/<int:flow_id>/evaluate-readiness",
        "/api/simple-operator/<int:flow_id>/approve-run",
        "/api/simple-operator/<int:flow_id>/track",
    ):
        check(route in dashboard, "simple operator route exists: {}".format(route))

    expectations = {
        "/api/simple-operator/request": "confirm_create",
        "generate_simple_operator_draft_route": "confirm_generate",
        "update_simple_operator_draft_route": "confirm_generate",
        "prepare_simple_operator_work_packet_route": "confirm_prepare",
        "evaluate_simple_operator_readiness_route": "confirm_evaluate",
        "approve_simple_operator_run_route": "confirm_run",
    }
    for marker, confirmation in expectations.items():
        section = route_section(dashboard, marker)
        check(confirmation in section, "{} requires {}".format(marker, confirmation))

    approve_section = route_section(dashboard, "approve_simple_operator_run_route")
    for phrase in (
        "payload.get(\"confirm_run\") is not True",
        "execution_mode != \"one_packet\"",
        "simple_run_blockers",
        "_execute_factory_task",
        "len(packet_tasks)",
        "_safe_send_operator_notification",
        "simple_flow_run_started",
        "simple_flow_run_passed",
        "simple_flow_run_failed",
        "simple_flow_blocked",
        "create_intervention",
    ):
        check(phrase in approve_section, "approve-run contains {}".format(phrase))

    for forbidden in (
        "/api/tasks/auto-run",
        "auto_run_tasks(",
        "mark_packet_trusted(",
        "set_execution_mode(",
        "continue_work_packet(",
        "retryOneTask",
    ):
        check(forbidden not in approve_section, "approve-run avoids {}".format(forbidden))


def verify_ui():
    template = read_file("templates/index.html")
    app = read_file("static/js/app.js")
    style = read_file("static/style.css")

    for phrase in (
        "simple-operator-flow-panel",
        "Simple Operator Flow",
        "Input → Draft → Approve → Execute one selected item → Track",
        "simple-operator-request",
        "simple-operator-draft",
        "Approve & Run One",
        "/api/simple-operator/status",
        "confirm_create",
        "confirm_generate",
        "confirm_prepare",
        "confirm_evaluate",
        "confirm_run",
    ):
        check(phrase in template + app, "UI contains {}".format(phrase))

    for function_name in (
        "loadSimpleOperatorStatus",
        "renderSimpleOperatorFlow",
        "createSimpleOperatorRequest",
        "generateSimpleOperatorDraft",
        "updateSimpleOperatorDraft",
        "prepareSimpleOperatorWorkPacket",
        "evaluateSimpleOperatorReadiness",
        "approveSimpleOperatorRun",
        "trackSimpleOperatorFlow",
    ):
        check(function_name in app, "app defines {}".format(function_name))

    check("NexusCore.confirmAction" in app, "UI uses NexusCore.confirmAction")
    check("simple-operator-flow-panel" in style, "Simple Operator styling exists")
    check("btn-lg" in template, "Simple Operator panel uses large mobile-friendly buttons")
    check("<details" in app, "advanced tracking details are collapsed")
    check("stdout_snippet" in app and "stderr_snippet" in app, "tracking renders stdout/stderr snippets")
    check("changed_files" in app, "tracking renders changed files")
    check("verification_result" in app, "tracking renders verification result")
    check("Report path" in app, "tracking renders report path when available")

    check(re.search(r"\balert\s*\(", app + template) is None, "no native alert added")
    check(re.search(r"\bconfirm\s*\(", app + template) is None, "no native confirm added")


def verify_safety_static():
    shell_true = []
    popen = []
    for relative_path in iter_python_files(["dashboard.py", "engine.py", "src"]):
        if has_shell_true(relative_path):
            shell_true.append(relative_path)
        if relative_path == "dashboard.py" or relative_path.startswith("src/services/"):
            if has_popen(relative_path):
                popen.append(relative_path)
    check(not shell_true, "no shell=True AST calls in dashboard.py engine.py src")
    check(not popen, "no subprocess.Popen in dashboard.py or src/services")

    combined_app = "\n".join(
        read_file(path)
        for path in (
            "dashboard.py",
            "static/js/app.js",
            "templates/index.html",
            "src/services/simple_operator_flow.py",
        )
    )
    for forbidden in (
        "Discord can execute",
        "discord command execution",
        "Auto-Pilot unlocked",
        "Auto-Pilot is enabled",
        "git commit",
        "git merge",
        "git push",
        "git reset",
        "git clean",
        "git rebase",
        "git stash",
        "git tag",
        "delete branch",
    ):
        check(forbidden not in combined_app, "simple flow code/UI avoid unsafe claim/control: {}".format(forbidden))


def verify_docs_and_preflight():
    combined_docs = "\n".join(
        read_file(path)
        for path in (
            "docs/SPRINT_4_PLAN.md",
            "docs/WORKFLOW_LOCK.md",
            "docs/CHAT_HANDOFF.md",
            "docs/OPERATOR_RUNBOOK.md",
            "docs/PROMPTING_GUIDE.md",
        )
    )
    for phrase in (
        "Simple Operator Flow is the primary",
        "Input -> Draft -> Approve -> Execute one selected item -> Track",
        "Advanced modules remain available",
        "Execution requires explicit approval",
        "Auto-Pilot remains locked",
        "Discord remains capture/notification-only",
        "Trusted Packet Mode",
        "Git Explorer remains read-only",
        "Branch Per Packet remains narrow",
        "confirm_run=true",
    ):
        check(phrase in combined_docs, "docs mention {}".format(phrase))

    preflight = read_file("scripts/nexus_preflight.py")
    check("src/services/simple_operator_flow.py" in preflight, "preflight compiles simple operator service")
    import scripts.nexus_preflight as preflight_module

    discovered = preflight_module.discover_packet_verifiers()
    check("scripts/verify_factory_packet_040.py" in discovered.get(40, []), "packet 040 verifier is discoverable")


def main():
    verify_service()
    verify_routes()
    verify_ui()
    verify_safety_static()
    verify_docs_and_preflight()
    if FAILURES:
        print("FAIL: Packet 040 verification failed")
        return 1
    print("PASS: Packet 040 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
