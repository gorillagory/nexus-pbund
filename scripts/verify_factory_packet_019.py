import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import dashboard as dashboard_module  # noqa: E402
import engine as engine_module  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from engine import NexusEngine  # noqa: E402
from models import (  # noqa: E402
    ExecutionChangedFile,
    ExecutionRun,
    FactoryEvent,
    Task,
    WorkPacket,
    WorkPacketTask,
    Workspace,
)
from src.services.codex_runner import CodexExecutionResult  # noqa: E402


FAILURES = []


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

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None


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
        if model is ExecutionRun:
            for run in self.execution_runs:
                if run.id == item_id:
                    return run
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
        if entity is ExecutionChangedFile:
            return FakeExecuteResult(list(self.changed_files))
        if entity is Workspace:
            return FakeExecuteResult([self.workspace])
        return FakeExecuteResult([])

    def _assign_id(self, obj):
        if not hasattr(obj, "id") or getattr(obj, "id", None) is not None:
            return
        model = obj.__class__
        next_id = self._next_ids.get(model, 1)
        obj.id = next_id
        self._next_ids[model] = next_id + 1


class FakeDBContext:
    def __init__(self, session):
        self.session = session

    def __iter__(self):
        return self

    def __next__(self):
        return self.session

    def close(self):
        self.session.close()


class FakeRunner:
    calls = []
    failures = set()

    def __init__(self, timeout_factory=None):
        self.timeout_factory = timeout_factory

    def run(self, prompt, workspace_path, task_id=None):
        FakeRunner.calls.append({"prompt": prompt, "workspace_path": workspace_path, "task_id": task_id})
        failed = task_id in self.failures
        return CodexExecutionResult(
            status="failed" if failed else "success",
            stdout="" if failed else "PACKET_019_RETRY_OK\n",
            stderr="PACKET_019_FAILURE\n" if failed else "",
            returncode=1 if failed else 0,
            timeout_seconds=45,
            execution_time=0.01,
            token_usage={},
            command=["codex", "exec", prompt],
        )


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


def make_task(task_id, status="todo"):
    return Task(
        id=task_id,
        workspace_id=123,
        title="Task {}".format(task_id),
        description='codex "Do not modify files. Print exactly: TASK_{}_OK"'.format(task_id),
        status=status,
    )


def make_dashboard(session, mode):
    original_chat_store = engine_module.ChatSessionStore
    engine_module.ChatSessionStore = NoopChatSessionStore
    engine = NexusEngine(PROJECT_ROOT)
    engine.settings["execution_mode"] = mode

    def save_settings(new_settings):
        engine.settings.update(new_settings)
        return {"status": "success", "settings": engine.public_settings()}

    engine.save_settings = save_settings
    dashboard = NexusDashboard(engine)
    dashboard.app.config["TESTING"] = True
    engine_module.ChatSessionStore = original_chat_store
    return dashboard, dashboard.app.test_client()


def patch_dashboard(session):
    originals = {
        "get_db": dashboard_module.get_db,
        "get_workspace_id": dashboard_module.get_workspace_id,
        "CodexRunner": dashboard_module.CodexRunner,
        "summarize_git_changes": dashboard_module.summarize_git_changes,
    }
    dashboard_module.get_db = lambda: FakeDBContext(session)
    dashboard_module.get_workspace_id = lambda local_path: 123
    dashboard_module.CodexRunner = FakeRunner
    dashboard_module.summarize_git_changes = lambda workspace_path: {
        "is_git_repo": True,
        "is_dirty": False,
        "changed_files": [{"path": "example.txt", "status": "M"}],
        "diff_stat": "example.txt | 1 +",
    }
    return originals


def restore_dashboard(originals):
    for name, value in originals.items():
        setattr(dashboard_module, name, value)


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    ui = app_js + "\n" + template
    for marker in (
        "/api/factory/runs/<int:run_id>",
        "/api/tasks/<int:task_id>/factory-details",
        "mark-review-required",
        "retry-one",
        "/api/work-packets/<int:work_packet_id>/continue",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))
    for marker in (
        "Latest Failed Run",
        "View Run Details",
        "Mark Review Required",
        "Retry One Task",
        "Continue Packet",
    ):
        check(marker in ui, "recovery UI contains {}".format(marker))

    recovery_section = section_between(app_js, "renderFactoryFailureRecovery", "async loadFactoryPreflightStatus")
    check("/api/tasks/auto-run" not in recovery_section, "recovery UI avoids auto-run endpoint")
    check("shell" + "=True" not in dashboard + app_js, "no shell true assignment")
    check("subprocess." + "Popen" not in dashboard, "no subprocess popen")
    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_key_pattern.search(app_js), "no raw frontend API key reads")


def verify_mark_review():
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task = make_task(1, status="todo")
    session = FakeSession(workspace, tasks=[task])
    originals = patch_dashboard(session)
    try:
        dashboard, client = make_dashboard(session, "manual")
        response = client.post(
            "/api/tasks/1/mark-review-required",
            json={"workspace_id": 123, "reason": "needs inspection"},
        )
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "mark-review-required HTTP 200")
        check(payload.get("status") == "success", "mark-review-required success")
        check(task.status == "review", "mark-review-required updates task status")
        check(any(event.event_type == "task_marked_review_required" for event in session.factory_events), "mark-review-required creates FactoryEvent")
    finally:
        restore_dashboard(originals)


def verify_retry_one():
    FakeRunner.calls = []
    FakeRunner.failures = set()
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task = make_task(2, status="review")
    unrelated = make_task(99, status="todo")
    session = FakeSession(workspace, tasks=[task, unrelated])
    originals = patch_dashboard(session)
    try:
        dashboard, client = make_dashboard(session, "one_task")
        response = client.post("/api/tasks/2/retry-one", json={"workspace_id": 123})
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "retry-one HTTP 200")
        check(payload.get("status") == "success", "retry-one success")
        check([call["task_id"] for call in FakeRunner.calls] == [2], "retry-one runs only selected task")
        check(task.status == "done", "retry-one marks selected task done")
        check(unrelated.status == "todo", "retry-one does not run unrelated task")
        check(len(session.execution_runs) == 1, "retry-one records ExecutionRun")
        check(session.factory_events, "retry-one records FactoryEvent")
    finally:
        restore_dashboard(originals)


def verify_continue_packet():
    FakeRunner.calls = []
    FakeRunner.failures = set()
    workspace = Workspace(id=123, name="test", local_path=PROJECT_ROOT)
    task_one = make_task(10, status="done")
    task_two = make_task(11, status="review")
    task_three = make_task(12, status="todo")
    unrelated = make_task(199, status="todo")
    packet = WorkPacket(id=5, workspace_id=123, title="Recovery Packet", status="failed")
    links = [
        WorkPacketTask(id=1, work_packet_id=5, task_id=10, position=1, status="completed"),
        WorkPacketTask(id=2, work_packet_id=5, task_id=11, position=2, status="failed"),
        WorkPacketTask(id=3, work_packet_id=5, task_id=12, position=3, status="skipped"),
    ]
    session = FakeSession(
        workspace,
        tasks=[task_one, task_two, task_three, unrelated],
        work_packets=[packet],
        packet_links=links,
    )
    originals = patch_dashboard(session)
    try:
        dashboard, client = make_dashboard(session, "one_packet")
        response = client.post("/api/work-packets/5/continue", json={"workspace_id": 123})
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "continue packet HTTP 200")
        check(payload.get("status") == "success", "continue packet success")
        check([call["task_id"] for call in FakeRunner.calls] == [11, 12], "continue packet resumes unfinished tasks only")
        check(task_one.status == "done", "continue packet does not rerun completed task")
        check(unrelated.status == "todo", "continue packet does not run unrelated task")
        check(links[1].status == "completed" and links[2].status == "completed", "continue packet marks resumed links complete")
        check(packet.status == "completed", "continue packet completes selected packet")
    finally:
        restore_dashboard(originals)


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
    verify_mark_review()
    verify_retry_one()
    verify_continue_packet()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 019 verification failed")
        return 1
    print("PASS: Packet 019 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
