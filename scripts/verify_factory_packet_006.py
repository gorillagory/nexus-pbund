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


def main():
    checks = []

    import engine as engine_module
    from engine import NexusEngine

    class DummyChatSessionStore:
        def __init__(self, max_messages=20):
            self.max_messages = max_messages

    engine_module.ChatSessionStore = DummyChatSessionStore
    engine = NexusEngine(os.getcwd())

    engine.settings = {"execution_mode": "manual"}
    manual_status = engine.automatic_analysis_status()
    manual_public = engine.public_settings()
    checks.append(engine.get_execution_mode() == "manual" or fail("manual mode not returned"))
    checks.append(
        engine.is_automatic_analysis_enabled() is False
        or fail("manual mode enables automatic analysis")
    )
    checks.append(
        manual_status.get("automatic_analysis_enabled") is False
        or fail("manual status enables automatic analysis")
    )
    checks.append(
        manual_public.get("automatic_analysis_enabled") is False
        or fail("manual public settings enables automatic analysis")
    )
    pass_line("manual mode disables automatic analysis")

    engine.settings = {"execution_mode": "one_task"}
    one_task_status = engine.automatic_analysis_status()
    one_task_public = engine.public_settings()
    checks.append(engine.get_execution_mode() == "one_task" or fail("one_task mode not returned"))
    checks.append(
        engine.is_automatic_analysis_enabled() is False
        or fail("one_task mode enables automatic analysis")
    )
    checks.append(
        one_task_status.get("automatic_analysis_enabled") is False
        or fail("one_task status enables automatic analysis")
    )
    checks.append(
        one_task_public.get("automatic_analysis_enabled") is False
        or fail("one_task public settings enables automatic analysis")
    )
    pass_line("one_task mode disables automatic analysis")

    engine.settings = {"execution_mode": "autopilot"}
    autopilot_status = engine.automatic_analysis_status()
    autopilot_public = engine.public_settings()
    checks.append(engine.get_execution_mode() == "autopilot" or fail("autopilot mode not returned"))
    checks.append(
        engine.is_automatic_analysis_enabled() is True
        or fail("autopilot mode does not enable automatic analysis")
    )
    checks.append(
        autopilot_status.get("automatic_analysis_enabled") is True
        or fail("autopilot status does not enable automatic analysis")
    )
    checks.append(
        autopilot_public.get("automatic_analysis_enabled") is True
        or fail("autopilot public settings does not enable automatic analysis")
    )
    pass_line("autopilot mode enables automatic analysis")

    engine.settings = {"execution_mode": "bad-mode"}
    checks.append(engine.get_execution_mode() == "manual" or fail("bad mode does not normalize to manual"))
    checks.append(
        engine.is_automatic_analysis_enabled() is False
        or fail("bad mode enables automatic analysis")
    )
    pass_line("invalid mode disables automatic analysis")

    engine_text = read_text("engine.py")
    checks.append(
        "Automatic analysis suppressed in Manual Mode" in engine_text
        or fail("watchdog suppression message missing")
    )
    checks.append(
        "is_automatic_analysis_enabled" in engine_text
        or fail("engine automatic analysis helper missing")
    )
    watcher_match = re.search(r"class\s+NexusWatcher\b(?P<body>.*)", engine_text, re.DOTALL)
    checks.append(watcher_match is not None or fail("NexusWatcher class missing"))
    if watcher_match is not None:
        watcher_body = watcher_match.group("body")
        checks.append(
            "is_automatic_analysis_enabled" in watcher_body
            or "_should_suppress_automatic_analysis" in watcher_body
            or fail("NexusWatcher does not reference automatic analysis guard")
        )
    pass_line("watchdog automatic analysis guard is present")

    dashboard_text = read_text("dashboard.py")
    execution_mode_route = re.search(
        r'"/api/execution-mode".*?def\s+set_execution_mode',
        dashboard_text,
        re.DOTALL,
    )
    checks.append(execution_mode_route is not None or fail("/api/execution-mode response logic missing"))
    checks.append(
        "automatic_analysis_enabled" in dashboard_text
        or fail("dashboard execution mode response omits automatic_analysis_enabled")
    )
    pass_line("dashboard exposes automatic analysis status")

    app_text = read_text("static/js/app.js")
    template_text = read_text("templates/index.html")
    ui_text = app_text + "\n" + template_text
    checks.append(
        "automatic analysis disabled" in ui_text
        or "automatic_analysis_enabled" in ui_text
        or fail("frontend automatic analysis status text missing")
    )
    pass_line("frontend indicates automatic analysis status")

    if not all(checks):
        return 1

    pass_line("Packet 006 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
