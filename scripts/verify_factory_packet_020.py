import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


import dashboard as dashboard_module  # noqa: E402
from models import ExecutionChangedFile, ExecutionRun, FactoryEvent, Task, WorkPacket, WorkPacketTask, Workspace  # noqa: E402
import verify_factory_packet_019 as packet019  # noqa: E402


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


def event_payload(event):
    try:
        payload = json.loads(event.payload_json or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    ui = app_js + "\n" + template

    for marker in (
        "operator_note",
        "triggered_by",
        "previous_status",
        "mark_review_required",
        "retry_one_task",
        "continue_packet",
        "latest_recovery_note",
        "recovery_events",
    ):
        check(marker in dashboard, "dashboard contains audit marker {}".format(marker))

    for marker in (
        "Operator note",
        "Recovery note",
        "Run Detail Panel",
        "Related recovery events",
        "factory-recovery-note",
    ):
        check(marker in ui, "recovery UI contains {}".format(marker))

    recovery_section = packet019.section_between(app_js, "renderFactoryFailureRecovery", "async loadFactoryPreflightStatus")
    check("/api/tasks/auto-run" not in recovery_section, "recovery UI avoids auto-run endpoint")
    check("shell" + "=True" not in dashboard + app_js, "no shell true assignment")
    check("subprocess." + "Popen" not in dashboard, "no subprocess popen")
    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_key_pattern.search(app_js), "no raw frontend API key reads")


def verify_mark_review_audit():
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task = packet019.make_task(1, status="failed")
    session = packet019.FakeSession(workspace, tasks=[task])
    originals = packet019.patch_dashboard(session)
    try:
        dashboard, client = packet019.make_dashboard(session, "manual")
        response = client.post(
            "/api/tasks/1/mark-review-required",
            json={
                "workspace_id": 123,
                "reason": "needs inspection",
                "operator_note": "review the failed diff before retry",
            },
        )
        payload = response.get_json(silent=True) or {}
        event = next((item for item in session.factory_events if item.event_type == "task_marked_review_required"), None)
        event_data = event_payload(event)
        check(response.status_code == 200, "mark-review-required HTTP 200")
        check(payload.get("status") == "success", "mark-review-required success")
        check(event_data.get("operator_note") == "review the failed diff before retry", "mark-review stores operator note")
        check(event_data.get("action") == "mark_review_required", "mark-review stores action")
        check(event_data.get("previous_status") == "failed", "mark-review stores previous status")
        check(event_data.get("triggered_by") == "operator", "mark-review stores operator trigger")
    finally:
        packet019.restore_dashboard(originals)


def verify_retry_one_audit():
    packet019.FakeRunner.calls = []
    packet019.FakeRunner.failures = set()
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task = packet019.make_task(2, status="failed")
    unrelated = packet019.make_task(99, status="todo")
    previous_run = ExecutionRun(
        id=77,
        workspace_id=123,
        task_id=2,
        status="failed",
        returncode=1,
        stderr="old failure",
        started_at=datetime.now(timezone.utc),
    )
    session = packet019.FakeSession(workspace, tasks=[task, unrelated])
    session.execution_runs.append(previous_run)
    originals = packet019.patch_dashboard(session)
    try:
        dashboard, client = packet019.make_dashboard(session, "one_task")
        response = client.post(
            "/api/tasks/2/retry-one",
            json={
                "workspace_id": 123,
                "operator_note": "retry after reviewing failure",
                "reason": "operator retry",
            },
        )
        payload = response.get_json(silent=True) or {}
        retry_event = next((item for item in session.factory_events if item.event_type == "task_retry_requested"), None)
        event_data = event_payload(retry_event)
        check(response.status_code == 200, "retry-one HTTP 200")
        check(payload.get("status") == "success", "retry-one success")
        check([call["task_id"] for call in packet019.FakeRunner.calls] == [2], "retry-one runs only selected task")
        check(unrelated.status == "todo", "retry-one does not run unrelated task")
        check(event_data.get("operator_note") == "retry after reviewing failure", "retry stores operator note")
        check(event_data.get("action") == "retry_one_task", "retry stores action")
        check(event_data.get("previous_status") == "failed", "retry stores previous status")
        check(event_data.get("triggered_by") == "operator", "retry stores operator trigger")
    finally:
        packet019.restore_dashboard(originals)


def verify_continue_packet_audit():
    packet019.FakeRunner.calls = []
    packet019.FakeRunner.failures = set()
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task_one = packet019.make_task(10, status="done")
    task_two = packet019.make_task(11, status="failed")
    task_three = packet019.make_task(12, status="todo")
    unrelated = packet019.make_task(199, status="todo")
    packet = WorkPacket(id=5, workspace_id=123, title="Recovery Packet", status="failed")
    links = [
        WorkPacketTask(id=1, work_packet_id=5, task_id=10, position=1, status="completed"),
        WorkPacketTask(id=2, work_packet_id=5, task_id=11, position=2, status="failed"),
        WorkPacketTask(id=3, work_packet_id=5, task_id=12, position=3, status="skipped"),
    ]
    session = packet019.FakeSession(
        workspace,
        tasks=[task_one, task_two, task_three, unrelated],
        work_packets=[packet],
        packet_links=links,
    )
    originals = packet019.patch_dashboard(session)
    try:
        dashboard, client = packet019.make_dashboard(session, "one_packet")
        response = client.post(
            "/api/work-packets/5/continue",
            json={
                "workspace_id": 123,
                "operator_note": "continue after reviewing packet failure",
                "reason": "operator continue",
            },
        )
        payload = response.get_json(silent=True) or {}
        continue_event = next((item for item in session.factory_events if item.event_type == "packet_run_continued"), None)
        event_data = event_payload(continue_event)
        check(response.status_code == 200, "continue packet HTTP 200")
        check(payload.get("status") == "success", "continue packet success")
        check([call["task_id"] for call in packet019.FakeRunner.calls] == [11, 12], "continue packet resumes unfinished tasks only")
        check(unrelated.status == "todo", "continue packet does not run unrelated task")
        check(event_data.get("operator_note") == "continue after reviewing packet failure", "continue stores operator note")
        check(event_data.get("action") == "continue_packet", "continue stores action")
        check(event_data.get("previous_status") == "failed", "continue stores previous status")
        check(event_data.get("triggered_by") == "operator", "continue stores operator trigger")
    finally:
        packet019.restore_dashboard(originals)


def verify_run_detail_audit():
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task = packet019.make_task(20, status="review")
    run = ExecutionRun(
        id=88,
        workspace_id=123,
        task_id=20,
        status="failed",
        returncode=1,
        stdout="detail stdout",
        stderr="detail stderr",
        started_at=datetime.now(timezone.utc),
        total_tokens=12,
    )
    changed_file = ExecutionChangedFile(
        id=1,
        execution_run_id=88,
        file_path="example.py",
        change_type="M",
        insertions=1,
        deletions=0,
        diff_summary="example.py | 1 +",
    )
    failure_event = FactoryEvent(
        id=1,
        workspace_id=123,
        task_id=20,
        execution_run_id=88,
        event_type="codex_run_failed",
        message="Run failed",
        payload_json=json.dumps({"returncode": 1}),
        created_at=datetime.now(timezone.utc),
    )
    recovery_event = FactoryEvent(
        id=2,
        workspace_id=123,
        task_id=20,
        event_type="task_retry_requested",
        message="Retry requested",
        payload_json=json.dumps(
            {
                "action": "retry_one_task",
                "operator_note": "audit detail note",
                "previous_status": "failed",
                "triggered_by": "operator",
            }
        ),
        created_at=datetime.now(timezone.utc),
    )
    session = packet019.FakeSession(workspace, tasks=[task])
    session.execution_runs.append(run)
    session.changed_files.append(changed_file)
    session.factory_events.extend([failure_event, recovery_event])
    originals = packet019.patch_dashboard(session)
    try:
        dashboard, client = packet019.make_dashboard(session, "manual")
        response = client.get("/api/factory/runs/88")
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "run detail HTTP 200")
        check(payload.get("status") == "success", "run detail success")
        check(payload.get("changed_files"), "run detail includes changed files")
        check(payload.get("recovery_events"), "run detail includes recovery events")
        check((payload.get("latest_recovery_note") or {}).get("note") == "audit detail note", "run detail includes latest recovery note")
        check((payload.get("latest_failure_event") or {}).get("event_type") == "codex_run_failed", "run detail includes latest failure event")
    finally:
        packet019.restore_dashboard(originals)


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
    verify_source_text()
    verify_mark_review_audit()
    verify_retry_one_audit()
    verify_continue_packet_audit()
    verify_run_detail_audit()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 020 verification failed")
        return 1
    print("PASS: Packet 020 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
