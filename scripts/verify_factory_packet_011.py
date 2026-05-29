#!/usr/bin/env python3
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def read_file(path):
    with open(os.path.join(ROOT_DIR, path), "r", encoding="utf-8") as file:
        return file.read()


def pass_line(message):
    print("PASS {}".format(message))


class DummyChatSessionStore:
    def __init__(self, *args, **kwargs):
        pass


class FakeWorkspace:
    def __init__(self, workspace_id, local_path):
        self.id = workspace_id
        self.local_path = local_path


class FakeTask:
    def __init__(self, task_id, workspace_id, title, description):
        self.id = task_id
        self.workspace_id = workspace_id
        self.title = title
        self.description = description
        self.status = "todo"


class FakeDB:
    def __init__(self, dashboard_module, workspace, task):
        self.dashboard_module = dashboard_module
        self.workspace = workspace
        self.task = task
        self.objects = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.next_id = 1000

    def get(self, model, object_id):
        if model is self.dashboard_module.Workspace and object_id == self.workspace.id:
            return self.workspace
        if model is self.dashboard_module.Task and object_id == self.task.id:
            return self.task
        return None

    def add(self, obj):
        self.objects.append(obj)

    def add_all(self, objects):
        self.objects.extend(objects)

    def commit(self):
        self.commits += 1
        for obj in self.objects:
            if getattr(obj, "id", None) is None:
                try:
                    obj.id = self.next_id
                except Exception:
                    pass
                self.next_id += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self.next_id
            self.next_id += 1

    def close(self):
        self.closed = True

    def query(self, *args, **kwargs):
        raise AssertionError("run-one route should not need query() in this verifier")

    def by_type(self, model):
        return [obj for obj in self.objects if isinstance(obj, model)]


class FakeDBContext:
    def __init__(self, db):
        self.db = db

    def __iter__(self):
        return self

    def __next__(self):
        return self.db

    def close(self):
        self.db.close()


class FakeRunner:
    calls = []
    result = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def run(self, prompt, workspace_path, task_id=None):
        FakeRunner.calls.append(
            {"prompt": prompt, "workspace_path": workspace_path, "task_id": task_id}
        )
        return FakeRunner.result


@contextmanager
def patched_attr(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def import_checks():
    from models import ExecutionChangedFile, ExecutionRun, FactoryEvent

    assert_true(ExecutionRun is not None, "ExecutionRun import failed")
    assert_true(ExecutionChangedFile is not None, "ExecutionChangedFile import failed")
    assert_true(FactoryEvent is not None, "FactoryEvent import failed")
    pass_line("model imports")


def static_dashboard_checks():
    text = read_file("dashboard.py")
    required = [
        "/api/tasks/run-one",
        "ExecutionRun",
        "ExecutionChangedFile",
        "git_changes_captured",
        "task_run_started",
        "codex_run_completed",
    ]
    for value in required:
        assert_true(value in text, "dashboard.py missing {}".format(value))
    assert_true(
        "FactoryEvent" in text or "create_factory_event" in text,
        "dashboard.py missing FactoryEvent/create_factory_event",
    )
    assert_true(
        "codex_run_failed" in text or "codex_run_timeout" in text,
        "dashboard.py missing failure/timeout event",
    )
    pass_line("dashboard run-one recording text")


def safety_checks():
    source_paths = []
    for relative in ("dashboard.py", "engine.py"):
        source_paths.append(relative)
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "src")):
        dirnames[:] = [
            name for name in dirnames if name not in {".git", "__pycache__", ".pytest_cache"}
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                source_paths.append(os.path.relpath(os.path.join(dirpath, filename), ROOT_DIR))

    for relative in source_paths:
        text = read_file(relative)
        assert_true("shell=True" not in text, "{} contains shell=True".format(relative))

    for relative in ("dashboard.py",):
        text = read_file(relative)
        assert_true(
            "subprocess.Popen" not in text,
            "{} contains subprocess.Popen".format(relative),
        )
    services_dir = os.path.join(ROOT_DIR, "src", "services")
    for dirpath, dirnames, filenames in os.walk(services_dir):
        dirnames[:] = [
            name for name in dirnames if name not in {".git", "__pycache__", ".pytest_cache"}
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                relative = os.path.relpath(os.path.join(dirpath, filename), ROOT_DIR)
                text = read_file(relative)
                assert_true(
                    "subprocess.Popen" not in text,
                    "{} contains subprocess.Popen".format(relative),
                )

    for relative in ("dashboard.py", "engine.py"):
        text = read_file(relative)
        assert_true(
            "return self.engine.settings" not in text,
            "{} returns raw engine settings".format(relative),
        )

    frontend = read_file("static/js/app.js")
    raw_key_pattern = re.compile(
        r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)"
    )
    assert_true(
        raw_key_pattern.search(frontend) is None,
        "frontend reads raw API key fields",
    )
    pass_line("safety checks")


def make_app_and_db(result, workspace_path, task_status="todo"):
    import dashboard as dashboard_module
    import engine as engine_module

    workspace = FakeWorkspace(123, workspace_path)
    task = FakeTask(
        456,
        123,
        "Packet 011 mocked task",
        'codex "Run only this mocked task"',
    )
    task.status = task_status
    fake_db = FakeDB(dashboard_module, workspace, task)
    FakeRunner.calls = []
    FakeRunner.result = result

    def fake_get_db():
        return FakeDBContext(fake_db)

    def fake_git_summary(repo_dir):
        return {
            "status_output": " M dashboard.py\n",
            "status_error": "",
            "diff_stat": " dashboard.py | 2 +-\n",
            "diff_stat_error": "",
            "changed_files": [{"status": "M", "path": "dashboard.py"}],
            "is_dirty": True,
            "is_git_repo": True,
        }

    patches = [
        patched_attr(engine_module, "ChatSessionStore", DummyChatSessionStore),
        patched_attr(dashboard_module, "get_workspace_id", lambda local_path: 123),
        patched_attr(dashboard_module, "get_db", fake_get_db),
        patched_attr(dashboard_module, "CodexRunner", FakeRunner),
        patched_attr(dashboard_module, "summarize_git_changes", fake_git_summary),
        patched_attr(dashboard_module, "_send_factory_discord_notification", lambda message: False),
    ]

    return dashboard_module, engine_module, workspace, task, fake_db, patches


def run_route_case(result, expected_status, expected_task_statuses):
    with tempfile.TemporaryDirectory(prefix="packet011-") as workspace_path:
        (
            dashboard_module,
            engine_module,
            workspace,
            task,
            fake_db,
            patches,
        ) = make_app_and_db(result, workspace_path)

        exits = []
        try:
            for patch in patches:
                patch.__enter__()
                exits.append(patch)

            engine = engine_module.NexusEngine(workspace_path)
            engine.settings["execution_mode"] = "one_task"
            dashboard = dashboard_module.NexusDashboard(engine)
            client = dashboard.app.test_client()
            response = client.post(
                "/api/tasks/run-one",
                json={"workspace_id": workspace.id, "task_id": task.id},
            )
            data = response.get_json()
        finally:
            for patch in reversed(exits):
                patch.__exit__(None, None, None)

    assert_true(data is not None, "run-one response was not JSON")
    assert_true(
        data.get("status") == expected_status,
        "expected status {}, got {}".format(expected_status, data.get("status")),
    )
    assert_true(
        task.status in expected_task_statuses,
        "task status {} not in {}".format(task.status, expected_task_statuses),
    )
    return response, data, fake_db, task


def mocked_success_route_check():
    from models import ExecutionChangedFile, ExecutionRun, FactoryEvent

    result = SimpleNamespace(
        status="success",
        stdout="PACKET_011_MOCK_CODEX_OK",
        stderr="non fatal warning",
        returncode=0,
        timeout_seconds=60,
        execution_time=0.01,
        token_usage={"total_tokens": 1234, "input_tokens": 1000, "output_tokens": 234},
    )
    response, data, fake_db, task = run_route_case(result, "success", {"done", "Done"})
    assert_true(response.status_code == 200, "success route returned {}".format(response.status_code))
    assert_true(data.get("execution_run_id"), "response missing execution_run_id")
    assert_true(isinstance(data.get("git"), dict), "response missing git summary")
    assert_true("PACKET_011_MOCK_CODEX_OK" in data.get("stdout", ""), "stdout marker missing")
    assert_true(data.get("stderr") == "non fatal warning", "stderr warning not preserved")
    assert_true(len(FakeRunner.calls) == 1, "Codex runner called {} times".format(len(FakeRunner.calls)))
    assert_true(fake_db.by_type(ExecutionRun), "ExecutionRun was not captured")
    assert_true(fake_db.by_type(FactoryEvent), "FactoryEvent rows were not captured")
    assert_true(fake_db.by_type(ExecutionChangedFile), "ExecutionChangedFile rows were not captured")
    event_types = [getattr(event, "event_type", "") for event in fake_db.by_type(FactoryEvent)]
    assert_true("task_run_started" in event_types, "task_run_started event missing")
    assert_true("codex_run_completed" in event_types, "codex_run_completed event missing")
    assert_true("git_changes_captured" in event_types, "git_changes_captured event missing")
    assert_true("task_marked_done" in event_types, "task_marked_done event missing")
    assert_true(task.status in {"done", "Done"}, "success did not move task to done")
    pass_line("mocked success route records run, events, git changes, and done status")


def mocked_failure_route_check():
    from models import FactoryEvent

    result = SimpleNamespace(
        status="failed",
        stdout="failure output",
        stderr="hard failure",
        returncode=1,
        timeout_seconds=60,
        execution_time=0.02,
        token_usage={"total_tokens": 12},
    )
    response, data, fake_db, task = run_route_case(
        result, "failed", {"review", "Review", "review_required"}
    )
    assert_true(len(FakeRunner.calls) == 1, "failure runner called more than once")
    assert_true(
        response.status_code >= 400 or data.get("status") == "failed",
        "failure route returned silent success",
    )
    event_types = [getattr(event, "event_type", "") for event in fake_db.by_type(FactoryEvent)]
    assert_true("codex_run_failed" in event_types, "codex_run_failed event missing")
    assert_true(
        "task_marked_review_required" in event_types,
        "task_marked_review_required event missing",
    )
    assert_true(
        task.status in {"review", "Review", "review_required"},
        "failure did not move task to review",
    )
    pass_line("mocked failure route records failure and review status")


def frontend_checks():
    text = read_file("static/js/app.js")
    assert_true("/api/tasks/run-one" in text, "frontend missing run-one endpoint")
    assert_true(
        "loadFactoryConsole" in text or "/api/factory/status" in text,
        "frontend missing factory console refresh path",
    )
    match = re.search(r"async\s+runOneTask\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s{8}\}", text, re.S)
    assert_true(match is not None, "could not locate runOneTask body")
    assert_true(
        "/api/tasks/auto-run" not in match.group("body"),
        "runOneTask body calls auto-run",
    )
    pass_line("frontend run-one refresh checks")


def main():
    import_checks()
    static_dashboard_checks()
    safety_checks()
    mocked_success_route_check()
    mocked_failure_route_check()
    frontend_checks()
    print("PASS factory packet 011 verification complete")


if __name__ == "__main__":
    main()
