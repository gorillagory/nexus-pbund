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


def route_body(source, route):
    match = re.search(
        r'@self\.app\.route\("{}"[^)]*\)\s*\n\s*def\s+\w+\([^)]*\):(?P<body>.*?)(?=\n\s*@self\.app\.route|\n\s*def\s+|\n\s*class\s+|\Z)'.format(
            re.escape(route)
        ),
        source,
        re.DOTALL,
    )
    return match.group("body") if match else ""


def js_method_body(source, method_name):
    match = re.search(
        r"(?:async\s+)?{}\s*\([^)]*\)\s*\{{(?P<body>.*?)(?=\n    (?:async\s+)?[A-Za-z0-9_]+\s*\([^)]*\)\s*\{{|\n\}};)".format(
            re.escape(method_name)
        ),
        source,
        re.DOTALL,
    )
    return match.group("body") if match else ""


class DummyChatSessionStore:
    def __init__(self, *args, **kwargs):
        pass


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None


class FakeDB:
    def __init__(self, dashboard_module, workspace, work_packet=None, tasks=None, links=None):
        self.dashboard_module = dashboard_module
        self.workspace = workspace
        self.work_packet = work_packet
        self.tasks = {}
        for task in tasks or []:
            self.tasks[task.id] = task
        self.links = list(links or [])
        self.objects = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.next_id = 100

    def get(self, model, object_id):
        if model is self.dashboard_module.Workspace and object_id == self.workspace.id:
            return self.workspace
        if model is self.dashboard_module.WorkPacket and self.work_packet is not None:
            if object_id == self.work_packet.id:
                return self.work_packet
        if model is self.dashboard_module.Task:
            return self.tasks.get(object_id)
        return None

    def add(self, obj):
        self.objects.append(obj)
        self._track(obj)

    def add_all(self, objects):
        for obj in objects:
            self.add(obj)

    def flush(self):
        self._assign_ids()

    def commit(self):
        self.commits += 1
        self._assign_ids()

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self.next_id
            self.next_id += 1
        self._track(obj)

    def close(self):
        self.closed = True

    def execute(self, statement):
        text = str(statement)
        if "work_packet_tasks" in text:
            return FakeScalarResult(sorted(self.links, key=lambda link: (link.position, link.id or 0)))
        if "execution_runs" in text:
            return FakeScalarResult(self.by_type(self.dashboard_module.ExecutionRun))
        if "factory_events" in text:
            return FakeScalarResult(self.by_type(self.dashboard_module.FactoryEvent))
        return FakeScalarResult([])

    def by_type(self, model):
        return [obj for obj in self.objects if isinstance(obj, model)]

    def _assign_ids(self):
        for obj in list(self.objects):
            if getattr(obj, "id", None) is None:
                obj.id = self.next_id
                self.next_id += 1
            self._track(obj)

    def _track(self, obj):
        if isinstance(obj, self.dashboard_module.WorkPacket):
            self.work_packet = obj
        elif isinstance(obj, self.dashboard_module.Task):
            self.tasks[obj.id] = obj
        elif isinstance(obj, self.dashboard_module.WorkPacketTask) and obj not in self.links:
            self.links.append(obj)


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
    results = []

    def __init__(self, *args, **kwargs):
        pass

    def run(self, prompt, workspace_path, task_id=None):
        FakeRunner.calls.append({"prompt": prompt, "workspace_path": workspace_path, "task_id": task_id})
        if not FakeRunner.results:
            raise AssertionError("No fake Codex result queued")
        return FakeRunner.results.pop(0)


@contextmanager
def patched_attr(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def make_result(status="success", returncode=0, marker="PACKET_012_OK"):
    return SimpleNamespace(
        status=status,
        stdout=marker + "\n",
        stderr="informational warning",
        returncode=returncode,
        timeout_seconds=60,
        execution_time=0.01,
        token_usage={"total_tokens": 123, "input_tokens": 100, "output_tokens": 23},
    )


def make_task(dashboard_module, task_id, workspace_id, title, prompt):
    return dashboard_module.Task(
        id=task_id,
        workspace_id=workspace_id,
        title=title,
        description='codex "{}"'.format(prompt),
        status="todo",
    )


def make_app_with_fake_db(db, workspace_path):
    import dashboard as dashboard_module
    import engine as engine_module

    def fake_get_db():
        return FakeDBContext(db)

    def fake_git_summary(repo_dir):
        return {
            "status_output": "",
            "status_error": "",
            "diff_stat": "",
            "diff_stat_error": "",
            "changed_files": [],
            "is_dirty": False,
            "is_git_repo": True,
        }

    patches = [
        patched_attr(engine_module, "ChatSessionStore", DummyChatSessionStore),
        patched_attr(dashboard_module, "get_workspace_id", lambda local_path: db.workspace.id),
        patched_attr(dashboard_module, "get_db", fake_get_db),
        patched_attr(dashboard_module, "CodexRunner", FakeRunner),
        patched_attr(dashboard_module, "summarize_git_changes", fake_git_summary),
        patched_attr(dashboard_module, "_send_factory_discord_notification", lambda message: False),
    ]

    exits = []
    for patch in patches:
        patch.__enter__()
        exits.append(patch)

    engine = engine_module.NexusEngine(workspace_path)
    engine.settings["execution_mode"] = "one_packet"
    dashboard = dashboard_module.NexusDashboard(engine)
    return dashboard_module, dashboard.app.test_client(), exits


def close_patches(exits):
    for patch in reversed(exits):
        patch.__exit__(None, None, None)


def execution_mode_checks():
    from engine import NexusEngine, normalize_execution_mode

    assert_true(normalize_execution_mode("one_packet") == "one_packet", "one_packet not normalized")
    engine = NexusEngine.__new__(NexusEngine)
    engine.settings = {"execution_mode": "one_packet"}
    assert_true(engine.get_execution_mode() == "one_packet", "one_packet not preserved")
    assert_true(engine.is_automatic_analysis_enabled() is False, "one_packet enabled automatic analysis")
    public = engine.public_settings()
    assert_true(public.get("execution_mode") == "one_packet", "public_settings missing one_packet")
    assert_true(public.get("automatic_analysis_enabled") is False, "public_settings enabled analysis")
    pass_line("one_packet execution mode is safe")


def static_route_checks():
    text = read_file("dashboard.py")
    assert_true("/api/work-packets/run" in text, "packet run route missing")
    assert_true("/api/work-packets/cancel-run" in text, "cancel route missing")
    assert_true("/api/work-packets/<int:work_packet_id>/status" in text, "packet status route missing")
    body = route_body(text, "/api/work-packets/run")
    assert_true(body, "packet run body missing")
    assert_true("/api/tasks/auto-run" not in body, "packet runner calls auto-run")
    assert_true("/api/execute-codex" not in body, "packet runner calls execute-codex")
    for event_type in (
        "packet_run_started",
        "packet_task_started",
        "packet_task_completed",
        "packet_task_failed",
        "packet_task_skipped",
        "packet_run_completed",
        "packet_run_failed",
        "packet_cancel_requested",
    ):
        assert_true(event_type in text, "missing event {}".format(event_type))
    pass_line("packet runner routes and events are present")


def staging_check():
    import dashboard as dashboard_module

    with tempfile.TemporaryDirectory(prefix="packet012-stage-") as workspace_path:
        workspace = dashboard_module.Workspace(id=1, name="repo", local_path=workspace_path)
        db = FakeDB(dashboard_module, workspace)
        FakeRunner.calls = []
        FakeRunner.results = []
        dashboard_module, client, exits = make_app_with_fake_db(db, workspace_path)
        try:
            response = client.post(
                "/api/work-packets/stage",
                json={
                    "workspace_id": 1,
                    "packet_text": '# Packet 012\n\nTask 1\ncodex "first"\n\nTask 2\ncodex "second"',
                },
            )
            data = response.get_json()
        finally:
            close_patches(exits)

    assert_true(response.status_code == 200, "stage returned {}".format(response.status_code))
    assert_true(data.get("work_packet_id"), "stage response missing work_packet_id")
    assert_true(len(db.by_type(dashboard_module.WorkPacketTask)) == 2, "stage did not create packet task links")
    pass_line("work packet staging creates packet and task associations")


def successful_packet_run_check():
    import dashboard as dashboard_module

    with tempfile.TemporaryDirectory(prefix="packet012-success-") as workspace_path:
        workspace = dashboard_module.Workspace(id=1, name="repo", local_path=workspace_path)
        work_packet = dashboard_module.WorkPacket(id=10, workspace_id=1, title="Packet 012", status="staged")
        task_one = make_task(dashboard_module, 11, 1, "Task One", "first")
        task_two = make_task(dashboard_module, 12, 1, "Task Two", "second")
        unrelated = make_task(dashboard_module, 99, 1, "Unrelated", "do not run")
        links = [
            dashboard_module.WorkPacketTask(id=21, work_packet_id=10, task_id=11, position=1, status="staged"),
            dashboard_module.WorkPacketTask(id=22, work_packet_id=10, task_id=12, position=2, status="staged"),
        ]
        db = FakeDB(dashboard_module, workspace, work_packet, [task_one, task_two, unrelated], links)
        FakeRunner.calls = []
        FakeRunner.results = [make_result(marker="FIRST_OK"), make_result(marker="SECOND_OK")]
        dashboard_module, client, exits = make_app_with_fake_db(db, workspace_path)
        try:
            response = client.post("/api/work-packets/run", json={"workspace_id": 1, "work_packet_id": 10})
            data = response.get_json()
        finally:
            close_patches(exits)

    assert_true(response.status_code == 200, "success packet run returned {}".format(response.status_code))
    assert_true(data.get("status") == "success", "packet run was not success")
    assert_true(work_packet.status == "completed", "work packet not completed")
    assert_true(len(FakeRunner.calls) == 2, "expected two task runs")
    assert_true([call["task_id"] for call in FakeRunner.calls] == [11, 12], "unexpected tasks executed")
    assert_true(99 not in [call["task_id"] for call in FakeRunner.calls], "unrelated task executed")
    assert_true(len(db.by_type(dashboard_module.ExecutionRun)) == 2, "execution runs not recorded")
    event_types = [getattr(event, "event_type", "") for event in db.by_type(dashboard_module.FactoryEvent)]
    assert_true("packet_run_completed" in event_types, "packet_run_completed missing")
    assert_true("packet_task_completed" in event_types, "packet_task_completed missing")
    pass_line("mocked successful packet run executes only linked tasks")


def failed_packet_run_check():
    import dashboard as dashboard_module

    with tempfile.TemporaryDirectory(prefix="packet012-fail-") as workspace_path:
        workspace = dashboard_module.Workspace(id=1, name="repo", local_path=workspace_path)
        work_packet = dashboard_module.WorkPacket(id=20, workspace_id=1, title="Packet 012 Fail", status="staged")
        task_one = make_task(dashboard_module, 31, 1, "Task One", "first")
        task_two = make_task(dashboard_module, 32, 1, "Task Two", "second")
        task_three = make_task(dashboard_module, 33, 1, "Task Three", "third")
        links = [
            dashboard_module.WorkPacketTask(id=41, work_packet_id=20, task_id=31, position=1, status="staged"),
            dashboard_module.WorkPacketTask(id=42, work_packet_id=20, task_id=32, position=2, status="staged"),
            dashboard_module.WorkPacketTask(id=43, work_packet_id=20, task_id=33, position=3, status="staged"),
        ]
        db = FakeDB(dashboard_module, workspace, work_packet, [task_one, task_two, task_three], links)
        FakeRunner.calls = []
        FakeRunner.results = [make_result(marker="FIRST_OK"), make_result(status="failed", returncode=1, marker="FAIL")]
        dashboard_module, client, exits = make_app_with_fake_db(db, workspace_path)
        try:
            response = client.post("/api/work-packets/run", json={"workspace_id": 1, "work_packet_id": 20})
            data = response.get_json()
        finally:
            close_patches(exits)

    assert_true(response.status_code >= 400 or data.get("status") == "failed", "failure was silent success")
    assert_true(data.get("status") == "failed", "packet run status was not failed")
    assert_true(work_packet.status == "failed", "work packet not failed")
    assert_true([call["task_id"] for call in FakeRunner.calls] == [31, 32], "packet did not stop after failure")
    assert_true(links[2].status == "skipped", "remaining task was not skipped")
    event_types = [getattr(event, "event_type", "") for event in db.by_type(dashboard_module.FactoryEvent)]
    assert_true("packet_task_failed" in event_types, "packet_task_failed missing")
    assert_true("packet_task_skipped" in event_types, "packet_task_skipped missing")
    assert_true("packet_run_failed" in event_types, "packet_run_failed missing")
    pass_line("mocked failed packet run stops at first failure")


def frontend_checks():
    app_text = read_file("static/js/app.js")
    html_text = read_file("templates/index.html")
    combined = app_text + "\n" + html_text
    assert_true("Run Packet" in combined, "Run Packet UI missing")
    assert_true("Supervised Packet Runner" in combined, "Supervised Packet Runner text missing")
    assert_true("/api/work-packets/run" in app_text, "frontend packet run endpoint missing")
    body = js_method_body(app_text, "runWorkPacket")
    assert_true(body, "runWorkPacket method missing")
    assert_true("/api/tasks/auto-run" not in body, "runWorkPacket calls auto-run")
    pass_line("frontend packet runner UI is present and bounded")


def safety_checks():
    source_paths = ["dashboard.py", "engine.py"]
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "src")):
        dirnames[:] = [name for name in dirnames if name not in {".git", "__pycache__"}]
        for filename in filenames:
            if filename.endswith(".py"):
                source_paths.append(os.path.relpath(os.path.join(dirpath, filename), ROOT_DIR))
    for relative in source_paths:
        assert_true("shell=True" not in read_file(relative), "{} contains shell=True".format(relative))
    for relative in ["dashboard.py"]:
        assert_true("subprocess.Popen" not in read_file(relative), "{} contains subprocess.Popen".format(relative))
    services_dir = os.path.join(ROOT_DIR, "src", "services")
    for dirpath, dirnames, filenames in os.walk(services_dir):
        dirnames[:] = [name for name in dirnames if name not in {".git", "__pycache__"}]
        for filename in filenames:
            if filename.endswith(".py"):
                relative = os.path.relpath(os.path.join(dirpath, filename), ROOT_DIR)
                assert_true("subprocess.Popen" not in read_file(relative), "{} contains Popen".format(relative))
    for relative in ("dashboard.py", "engine.py"):
        assert_true("return self.engine.settings" not in read_file(relative), "{} returns raw settings".format(relative))
    pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    assert_true(pattern.search(read_file("static/js/app.js")) is None, "frontend reads raw API key fields")
    pass_line("safety checks")


def main():
    execution_mode_checks()
    static_route_checks()
    staging_check()
    successful_packet_run_check()
    failed_packet_run_check()
    frontend_checks()
    safety_checks()
    print("PASS factory packet 012 verification complete")


if __name__ == "__main__":
    main()
