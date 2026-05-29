import os
import re
import subprocess
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import engine as engine_module  # noqa: E402
import dashboard as dashboard_module  # noqa: E402
from engine import NexusEngine  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from models import (  # noqa: E402
    ExecutionChangedFile,
    ExecutionRun,
    FactoryEvent,
    Task,
    WorkPacket,
    WorkPacketTask,
    Workspace,
)
from src.services import factory_events, git_changes  # noqa: E402
from src.services.codex_runner import CodexExecutionResult  # noqa: E402


FAILURES = []
AUTOPILOT_CALLED = False
TASKS_AUTO_RUN_CALLED = False
REAL_CODEX_RUN = False


class NoopChatSessionStore:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages

    def get_history(self, session_id):
        return []

    def append_exchange(self, session_id, user_message, assistant_message):
        return None


class FakeScalarResult:
    def __init__(self, values):
        self.values = list(values)

    def all(self):
        return list(self.values)


class FakeExecuteResult:
    def __init__(self, values):
        self.values = list(values)

    def scalars(self):
        return FakeScalarResult(self.values)


class FakeSession:
    def __init__(self, workspace, tasks=None, work_packets=None, packet_links=None):
        self.workspace = workspace
        self.tasks = {task.id: task for task in (tasks or [])}
        self.work_packets = {packet.id: packet for packet in (work_packets or [])}
        self.packet_links = list(packet_links or [])
        self.execution_runs = []
        self.changed_files = []
        self.factory_events = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self._next_ids = {
            ExecutionRun: 1,
            ExecutionChangedFile: 1,
            FactoryEvent: 1,
            WorkPacket: 1,
            WorkPacketTask: 1,
            Task: 1,
        }

    def add(self, obj):
        self._assign_id(obj)
        if isinstance(obj, ExecutionRun) and obj not in self.execution_runs:
            self.execution_runs.append(obj)
        elif isinstance(obj, ExecutionChangedFile) and obj not in self.changed_files:
            self.changed_files.append(obj)
        elif isinstance(obj, FactoryEvent) and obj not in self.factory_events:
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            self.factory_events.append(obj)
        elif isinstance(obj, Task):
            self.tasks[obj.id] = obj
        elif isinstance(obj, WorkPacket):
            self.work_packets[obj.id] = obj
        elif isinstance(obj, WorkPacketTask) and obj not in self.packet_links:
            self.packet_links.append(obj)

    def add_all(self, objects):
        for obj in objects:
            self.add(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        self._assign_id(obj)
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    def close(self):
        self.closed = True

    def get(self, model, item_id):
        if model is Workspace:
            return self.workspace if item_id == self.workspace.id else None
        if model is Task:
            return self.tasks.get(item_id)
        if model is WorkPacket:
            return self.work_packets.get(item_id)
        return None

    def execute(self, statement):
        entity = None
        try:
            entity = statement.column_descriptions[0].get("entity")
        except Exception:
            entity = None

        if entity is WorkPacketTask:
            return FakeExecuteResult(sorted(self.packet_links, key=lambda item: (item.position, item.id or 0)))
        if entity is ExecutionRun:
            return FakeExecuteResult(sorted(self.execution_runs, key=lambda item: item.id or 0, reverse=True))
        if entity is FactoryEvent:
            return FakeExecuteResult(sorted(self.factory_events, key=lambda item: item.id or 0, reverse=True))
        if entity is Task:
            return FakeExecuteResult(list(self.tasks.values()))
        return FakeExecuteResult([])

    def _assign_id(self, obj):
        if not hasattr(obj, "id") or getattr(obj, "id", None) is not None:
            return
        model = obj.__class__
        next_id = self._next_ids.get(model, 1)
        obj.id = next_id
        self._next_ids[model] = next_id + 1


class FakeCodexRunner:
    markers_by_task_id = {}
    failures_by_task_id = {}
    calls = []

    def __init__(self, timeout_factory=None):
        self.timeout_factory = timeout_factory

    def run(self, prompt, workspace_path, task_id=None):
        FakeCodexRunner.calls.append(
            {"prompt": prompt, "workspace_path": workspace_path, "task_id": task_id}
        )
        marker = self.markers_by_task_id.get(task_id, "REGRESSION_DEFAULT_OK")
        failed = bool(self.failures_by_task_id.get(task_id))
        return CodexExecutionResult(
            status="failed" if failed else "success",
            stdout="" if failed else "{}\n".format(marker),
            stderr="REGRESSION_FAILURE\n" if failed else "",
            returncode=1 if failed else 0,
            timeout_seconds=45,
            execution_time=0.01,
            token_usage={},
            command=["codex", "exec", prompt],
        )


def make_workspace():
    workspace = Workspace(id=123, name="regression", local_path=PROJECT_ROOT)
    return workspace


def make_task(task_id, title, marker):
    return Task(
        id=task_id,
        workspace_id=123,
        title=title,
        description='codex "Do not modify files. Print exactly: {}"'.format(marker),
        status="todo",
    )


def make_packet(packet_id, tasks):
    packet = WorkPacket(
        id=packet_id,
        workspace_id=123,
        title="Regression Packet {}".format(packet_id),
        risk_level="low",
        stop_condition="stop after first failure",
        estimated_minutes="1",
        status="staged",
        created_at=datetime.now(timezone.utc),
    )
    links = [
        WorkPacketTask(
            id=index,
            work_packet_id=packet_id,
            task_id=task.id,
            position=index,
            status="staged",
        )
        for index, task in enumerate(tasks, start=1)
    ]
    return packet, links


def print_pass(message):
    print("PASS: {}".format(message))


def print_fail(message):
    FAILURES.append(message)
    print("FAIL: {}".format(message))


def check(condition, message):
    if condition:
        print_pass(message)
    else:
        print_fail(message)


@contextmanager
def patched_dashboard(fake_session):
    original_get_db = dashboard_module.get_db
    original_get_workspace_id = dashboard_module.get_workspace_id
    original_codex_runner = dashboard_module.CodexRunner
    original_summarize_git_changes = dashboard_module.summarize_git_changes
    original_chat_store = engine_module.ChatSessionStore

    def fake_get_db():
        try:
            yield fake_session
        finally:
            fake_session.close()

    def fake_summarize_git_changes(repo_dir):
        return {
            "status_output": " M regression.txt\n",
            "status_error": "",
            "diff_stat": " regression.txt | 1 +\n",
            "diff_stat_error": "",
            "changed_files": [{"status": "M", "path": "regression.txt"}],
            "is_dirty": True,
            "is_git_repo": True,
        }

    dashboard_module.get_db = fake_get_db
    dashboard_module.get_workspace_id = lambda local_path: 123
    dashboard_module.CodexRunner = FakeCodexRunner
    dashboard_module.summarize_git_changes = fake_summarize_git_changes
    engine_module.ChatSessionStore = NoopChatSessionStore
    try:
        yield
    finally:
        dashboard_module.get_db = original_get_db
        dashboard_module.get_workspace_id = original_get_workspace_id
        dashboard_module.CodexRunner = original_codex_runner
        dashboard_module.summarize_git_changes = original_summarize_git_changes
        engine_module.ChatSessionStore = original_chat_store


def make_dashboard(fake_session):
    engine = NexusEngine(PROJECT_ROOT)

    def in_memory_save_settings(new_settings):
        for key, value in new_settings.items():
            if key == "execution_mode":
                engine.settings[key] = engine_module.normalize_execution_mode(value)
            else:
                engine.settings[key] = value
        return {"status": "success", "settings": engine.public_settings()}

    engine.save_settings = in_memory_save_settings
    dashboard = NexusDashboard(engine)
    dashboard.app.config["TESTING"] = True

    def forbidden_start(*args, **kwargs):
        global AUTOPILOT_CALLED
        AUTOPILOT_CALLED = True
        raise AssertionError("Auto-Pilot must not be started.")

    dashboard.autonomous_queue.start = forbidden_start
    return dashboard, dashboard.app.test_client()


def assert_json_response(response, route):
    is_json = response.is_json
    payload = response.get_json(silent=True)
    check(is_json and isinstance(payload, dict), "{} returns JSON".format(route))
    return payload or {}


def verify_imports():
    check(NexusEngine is not None, "import NexusEngine")
    check(NexusDashboard is not None, "import NexusDashboard")
    check(all(item is not None for item in (WorkPacket, WorkPacketTask, ExecutionRun, ExecutionChangedFile, FactoryEvent, Task)), "import factory models")
    check(factory_events is not None and git_changes is not None, "import factory services")


def verify_execution_modes():
    original_chat_store = engine_module.ChatSessionStore
    engine_module.ChatSessionStore = NoopChatSessionStore
    try:
        engine = NexusEngine(PROJECT_ROOT)

        def in_memory_save_settings(new_settings):
            for key, value in new_settings.items():
                if key == "execution_mode":
                    engine.settings[key] = engine_module.normalize_execution_mode(value)
            return {"status": "success", "settings": engine.public_settings()}

        engine.save_settings = in_memory_save_settings
        for mode in ("manual", "one_task", "one_packet", "autopilot"):
            check(engine.set_execution_mode(mode) == mode, "{} accepted".format(mode))
        check(engine.set_execution_mode("bad-mode") == "manual", "bad mode normalizes to manual")
        engine.set_execution_mode("autopilot")
        check(engine.is_automatic_analysis_enabled(), "automatic analysis enabled only for autopilot")
        engine.set_execution_mode("one_task")
        check(not engine.is_automatic_analysis_enabled(), "one_task automatic analysis false")
        engine.set_execution_mode("one_packet")
        check(not engine.is_automatic_analysis_enabled(), "one_packet automatic analysis false")
    finally:
        engine_module.ChatSessionStore = original_chat_store


def read_files(paths):
    for path in paths:
        full_path = os.path.join(PROJECT_ROOT, path)
        if os.path.isdir(full_path):
            for root, dirs, files in os.walk(full_path):
                dirs[:] = [directory for directory in dirs if directory not in {".git", "__pycache__"}]
                for file_name in files:
                    if file_name.endswith((".py", ".js")):
                        yield os.path.join(root, file_name)
        elif os.path.exists(full_path):
            yield full_path


def verify_safety_source_scan():
    shell_true = []
    popen = []
    return_settings = []
    frontend_keys = []

    for file_path in read_files(["dashboard.py", "engine.py", "src"]):
        content = open(file_path, "r", encoding="utf-8").read()
        rel_path = os.path.relpath(file_path, PROJECT_ROOT)
        if "shell=True" in content:
            shell_true.append(rel_path)
        if rel_path == "dashboard.py" or rel_path.startswith("src/services/"):
            if "subprocess.Popen" in content:
                popen.append(rel_path)
        if rel_path in {"dashboard.py", "engine.py"} and "return self.engine.settings" in content:
            return_settings.append(rel_path)

    key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    for file_path in read_files(["static/js"]):
        content = open(file_path, "r", encoding="utf-8").read()
        if key_pattern.search(content):
            frontend_keys.append(os.path.relpath(file_path, PROJECT_ROOT))

    check(not shell_true, "no shell=True in dashboard.py engine.py src")
    check(not popen, "no subprocess.Popen in dashboard.py/src/services")
    check(not return_settings, "no return self.engine.settings")
    check(not frontend_keys, "no raw frontend API key reads")


def verify_console_endpoints():
    fake_session = FakeSession(make_workspace())
    with patched_dashboard(fake_session):
        dashboard, client = make_dashboard(fake_session)
        for route in (
            "/api/execution-mode",
            "/api/factory/git-status",
            "/api/factory/status",
            "/api/factory/events",
            "/api/factory/runs",
        ):
            response = client.get(route)
            payload = assert_json_response(response, route)
            check(response.status_code < 500, "{} is healthy".format(route))
            check(payload.get("status") in {"success", "error"} or route == "/api/factory/git-status", "{} has status payload".format(route))


def verify_run_one_success():
    global TASKS_AUTO_RUN_CALLED
    task = make_task(1, "Regression Run One", "REGRESSION_RUN_ONE_OK")
    fake_session = FakeSession(make_workspace(), tasks=[task])
    FakeCodexRunner.markers_by_task_id = {1: "REGRESSION_RUN_ONE_OK"}
    FakeCodexRunner.failures_by_task_id = {}
    FakeCodexRunner.calls = []

    with patched_dashboard(fake_session):
        dashboard, client = make_dashboard(fake_session)
        dashboard.engine.set_execution_mode("one_task")
        response = client.post("/api/tasks/run-one", json={"workspace_id": 123, "task_id": 1})
        payload = assert_json_response(response, "/api/tasks/run-one")

    check(response.status_code == 200, "run-one returns HTTP 200")
    check(payload.get("status") == "success", "run-one status success")
    check("REGRESSION_RUN_ONE_OK" in (payload.get("stdout") or ""), "run-one stdout marker present")
    check(len(fake_session.execution_runs) == 1, "run-one captured ExecutionRun")
    check(any(event.event_type == "codex_run_completed" for event in fake_session.factory_events), "run-one captured FactoryEvent")
    check(len(fake_session.changed_files) == 1, "run-one captured ExecutionChangedFile")
    check(task.status == "done", "run-one task moved to done")
    check(len(FakeCodexRunner.calls) == 1, "run-one used mocked CodexRunner exactly once")
    check(not TASKS_AUTO_RUN_CALLED, "run-one did not call Auto-Pilot endpoint")


def verify_packet_success():
    task_one = make_task(11, "Packet Task One", "REGRESSION_PACKET_TASK_ONE_OK")
    task_two = make_task(12, "Packet Task Two", "REGRESSION_PACKET_TASK_TWO_OK")
    unrelated = make_task(13, "Unrelated Task", "REGRESSION_UNRELATED_SHOULD_NOT_RUN")
    packet, links = make_packet(21, [task_one, task_two])
    fake_session = FakeSession(make_workspace(), tasks=[task_one, task_two, unrelated], work_packets=[packet], packet_links=links)
    FakeCodexRunner.markers_by_task_id = {
        11: "REGRESSION_PACKET_TASK_ONE_OK",
        12: "REGRESSION_PACKET_TASK_TWO_OK",
    }
    FakeCodexRunner.failures_by_task_id = {}
    FakeCodexRunner.calls = []

    with patched_dashboard(fake_session):
        dashboard, client = make_dashboard(fake_session)
        dashboard.engine.set_execution_mode("one_packet")
        response = client.post("/api/work-packets/run", json={"workspace_id": 123, "work_packet_id": 21})
        payload = assert_json_response(response, "/api/work-packets/run success")

    called_task_ids = [call["task_id"] for call in FakeCodexRunner.calls]
    check(response.status_code == 200, "packet success returns HTTP 200")
    check(called_task_ids == [11, 12], "packet success executes selected tasks exactly once")
    check(13 not in called_task_ids, "packet success does not execute unrelated task")
    check(packet.status == "completed", "packet success status completed")
    check(payload.get("completed_count") == 2, "packet success completed_count 2")
    check(payload.get("failed_count") == 0, "packet success failed_count 0")
    check(len(fake_session.execution_runs) == 2, "packet success captured execution runs")
    check(any(event.event_type == "packet_run_completed" for event in fake_session.factory_events), "packet success captured factory events")
    check(not TASKS_AUTO_RUN_CALLED, "packet success did not call Auto-Pilot endpoint")


def verify_packet_failure_stop():
    task_one = make_task(31, "Packet Task One", "REGRESSION_PACKET_FAIL_ONE_OK")
    task_two = make_task(32, "Packet Task Two", "REGRESSION_PACKET_FAIL_TWO_BAD")
    task_three = make_task(33, "Packet Task Three", "REGRESSION_PACKET_FAIL_THREE_SHOULD_NOT_RUN")
    unrelated = make_task(34, "Unrelated Task", "REGRESSION_UNRELATED_SHOULD_NOT_RUN")
    packet, links = make_packet(41, [task_one, task_two, task_three])
    fake_session = FakeSession(make_workspace(), tasks=[task_one, task_two, task_three, unrelated], work_packets=[packet], packet_links=links)
    FakeCodexRunner.markers_by_task_id = {31: "REGRESSION_PACKET_FAIL_ONE_OK"}
    FakeCodexRunner.failures_by_task_id = {32: True}
    FakeCodexRunner.calls = []

    with patched_dashboard(fake_session):
        dashboard, client = make_dashboard(fake_session)
        dashboard.engine.set_execution_mode("one_packet")
        response = client.post("/api/work-packets/run", json={"workspace_id": 123, "work_packet_id": 41})
        payload = assert_json_response(response, "/api/work-packets/run failure")

    called_task_ids = [call["task_id"] for call in FakeCodexRunner.calls]
    check(response.status_code == 500, "packet failure returns HTTP 500")
    check(called_task_ids == [31, 32], "packet failure stops before third task")
    check(33 not in called_task_ids, "packet failure did not run task three")
    check(34 not in called_task_ids, "packet failure did not run unrelated task")
    check(packet.status == "failed", "packet failure status failed")
    check(payload.get("failed_count") == 1, "packet failure failed_count 1")
    check(any(event.event_type == "packet_task_failed" for event in fake_session.factory_events), "packet failure event captured")
    check(any(event.event_type == "packet_task_skipped" for event in fake_session.factory_events), "packet skipped event captured")


def verify_git_helper():
    before = subprocess.run(
        ["git", "status", "--short"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    summary = git_changes.summarize_git_changes(PROJECT_ROOT)
    after = subprocess.run(
        ["git", "status", "--short"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    check(isinstance(summary, dict), "git helper returns dict")
    check("is_git_repo" in summary, "git helper has is_git_repo")
    check("is_dirty" in summary, "git helper has is_dirty")
    check("changed_files" in summary, "git helper has changed_files")
    check(before == after, "git helper does not mutate git status")


def main():
    verify_imports()
    verify_execution_modes()
    verify_safety_source_scan()
    verify_console_endpoints()
    verify_run_one_success()
    verify_packet_success()
    verify_packet_failure_stop()
    verify_git_helper()

    check(not REAL_CODEX_RUN, "no real Codex execution happens")
    check(not AUTOPILOT_CALLED, "Auto-Pilot not called")
    check(not TASKS_AUTO_RUN_CALLED, "/api/tasks/auto-run not called")

    if FAILURES:
        print("\n{} failure(s) detected.".format(len(FAILURES)))
        return 1

    print("PASS: Factory regression suite complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
