import os
import re
import sys
import tempfile


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


class FakeEngine:
    def __init__(self, target_dir):
        self.target_dir = target_dir
        self.state = {}
        self.telemetry_logger = None

    def get_execution_mode(self):
        return "one_task"

    def is_automatic_analysis_enabled(self):
        return False


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, workspace, task, dashboard_module):
        self.workspace = workspace
        self.task = task
        self.dashboard_module = dashboard_module

    def execute(self, statement):
        return FakeScalarResult(self.workspace)

    def get(self, model, object_id):
        if model is self.dashboard_module.Workspace and object_id == self.workspace.id:
            return self.workspace
        if model is self.dashboard_module.Task and object_id == self.task.id:
            return self.task
        return None

    def close(self):
        pass


class FakeWorkspace:
    def __init__(self, workspace_id, local_path):
        self.id = workspace_id
        self.local_path = local_path


class FakeTask:
    def __init__(self, task_id, workspace_id, description):
        self.id = task_id
        self.workspace_id = workspace_id
        self.description = description


class FakeCodexResult:
    status = "success"
    stdout = "mock stdout"
    stderr = "mock stderr is informational"
    returncode = 0
    timeout_seconds = 12
    execution_time = 0.25
    token_usage = {"total_tokens": 20578, "input_tokens": 100, "output_tokens": 50}


def verify_mocked_run_one_route():
    import dashboard as dashboard_module
    from src.services.cost_ledger import read_cost_events

    calls = []

    class FakeCodexRunner:
        def __init__(self, timeout_factory=None):
            self.timeout_factory = timeout_factory

        def run(self, prompt, workspace_path, task_id=None):
            calls.append(
                {
                    "prompt": prompt,
                    "workspace_path": workspace_path,
                    "task_id": task_id,
                }
            )
            return FakeCodexResult()

    original_get_db = dashboard_module.get_db
    original_codex_runner = dashboard_module.CodexRunner

    with tempfile.TemporaryDirectory() as root_dir:
        workspace = FakeWorkspace(1, root_dir)
        task = FakeTask(2, 1, 'Do exactly this:\ncodex "say hello"\n')
        session = FakeSession(workspace, task, dashboard_module)

        def fake_get_db():
            yield session

        try:
            dashboard_module.get_db = fake_get_db
            dashboard_module.CodexRunner = FakeCodexRunner

            dashboard = dashboard_module.NexusDashboard(FakeEngine(root_dir))
            client = dashboard.app.test_client()
            response = client.post(
                "/api/tasks/run-one",
                json={"workspace_id": 1, "task_id": 2},
            )
            data = response.get_json()
        finally:
            dashboard_module.get_db = original_get_db
            dashboard_module.CodexRunner = original_codex_runner

        if response.status_code != 200:
            return fail("run-one route returned HTTP {}".format(response.status_code))
        if data.get("status") != "success":
            return fail("run-one route did not return success")
        if data.get("returncode") != 0:
            return fail("run-one route did not return mocked returncode")
        if data.get("stdout") != "mock stdout":
            return fail("run-one route did not return mocked stdout")
        if data.get("stderr") != "mock stderr is informational":
            return fail("run-one route did not preserve stderr on success")
        if data.get("token_usage", {}).get("total_tokens") != 20578:
            return fail("run-one route did not return mocked token usage")
        if calls != [{"prompt": "say hello", "workspace_path": root_dir, "task_id": 2}]:
            return fail("run-one route did not call mocked CodexRunner exactly once")

        events = read_cost_events(root_dir, limit=10)
        if len(events) != 1:
            return fail("run-one route did not record one cost ledger event")
        if events[0].get("source") != "run_one":
            return fail("run-one cost ledger source mismatch")
        if events[0].get("total_tokens") != 20578:
            return fail("run-one cost ledger token total mismatch")

    pass_line("mocked run-one route succeeds once and records cost ledger event")
    return True


def main():
    checks = []

    from engine import NexusEngine, normalize_execution_mode

    checks.append(
        normalize_execution_mode("one_task") == "one_task"
        or fail("normalize_execution_mode does not accept one_task")
    )
    checks.append(
        normalize_execution_mode(" One_Task ") == "one_task"
        or fail("normalize_execution_mode does not normalize one_task case/space")
    )
    checks.append(
        normalize_execution_mode("one_packet") == "one_packet"
        or fail("normalize_execution_mode does not accept one_packet")
    )
    engine = NexusEngine.__new__(NexusEngine)
    engine.settings = {"execution_mode": "one_task"}
    checks.append(
        engine.get_execution_mode() == "one_task"
        or fail("get_execution_mode does not preserve one_task")
    )
    checks.append(
        engine.is_automatic_analysis_enabled() is False
        or fail("one_task enables automatic analysis")
    )
    pass_line("engine one_task mode is accepted without automatic analysis")

    engine.settings = {"execution_mode": "one_packet"}
    checks.append(
        engine.get_execution_mode() == "one_packet"
        or fail("get_execution_mode does not preserve one_packet")
    )
    checks.append(
        engine.is_automatic_analysis_enabled() is False
        or fail("one_packet enables automatic analysis")
    )
    pass_line("engine one_packet mode is accepted without automatic analysis")

    dashboard_text = read_text("dashboard.py")
    run_one_body = route_body(dashboard_text, "/api/tasks/run-one")
    shared_runner_body = dashboard_text
    checks.append(run_one_body or fail("/api/tasks/run-one route missing"))
    checks.append("shell=True" not in run_one_body or fail("run-one route uses shell=True"))
    checks.append(
        "subprocess.Popen" not in run_one_body
        and ".Popen(" not in run_one_body
        or fail("run-one route uses subprocess.Popen")
    )
    checks.append("autonomous_queue.start" not in run_one_body or fail("run-one starts Auto-Pilot"))
    checks.append("CodexRunner" in shared_runner_body or fail("run-one helper does not reference CodexRunner"))
    checks.append("append_cost_event" in shared_runner_body or fail("run-one helper does not record cost ledger"))
    checks.append("returncode != 0" in shared_runner_body or fail("run-one helper does not check returncode"))
    pass_line("dashboard run-one route is present and avoids shell/Popen/Auto-Pilot")

    app_text = read_text("static/js/app.js")
    run_one_js = js_method_body(app_text, "runOneTask")
    checks.append('"/api/tasks/run-one"' in app_text or fail("frontend run-one endpoint missing"))
    checks.append(run_one_js or fail("runOneTask frontend method missing"))
    checks.append(
        "/api/tasks/auto-run" not in run_one_js
        or fail("Run One Task frontend path calls Auto-Pilot")
    )
    checks.append(
        "/api/execute-codex" not in run_one_js
        or fail("Run One Task frontend path calls execute-codex")
    )
    checks.append("loadCostLedger" in run_one_js or fail("Run One Task path does not refresh cost ledger"))
    pass_line("frontend Run One Task path avoids Auto-Pilot and refreshes cost ledger")

    checks.append(verify_mocked_run_one_route())

    if not all(checks):
        return 1

    pass_line("Packet 009 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
