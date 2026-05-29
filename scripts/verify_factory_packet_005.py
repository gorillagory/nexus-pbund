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
    from engine import NexusEngine, normalize_execution_mode

    expected_modes = [
        (None, "manual"),
        ("", "manual"),
        ("manual", "manual"),
        (" Manual ", "manual"),
        ("one_task", "one_task"),
        (" One_Task ", "one_task"),
        ("one_packet", "one_packet"),
        (" One_Packet ", "one_packet"),
        ("autopilot", "autopilot"),
        ("bad", "manual"),
    ]
    for raw_value, expected in expected_modes:
        actual = normalize_execution_mode(raw_value)
        checks.append(
            actual == expected
            or fail("normalize_execution_mode({!r}) returned {!r}".format(raw_value, actual))
        )
    pass_line("execution mode normalization defaults invalid input to manual")

    class DummyChatSessionStore:
        def __init__(self, max_messages=20):
            self.max_messages = max_messages

    engine_module.ChatSessionStore = DummyChatSessionStore
    engine = NexusEngine(os.getcwd())
    engine.settings = {
        "provider": "gemini",
        "gemini_api_key": "SECRET_GEMINI",
        "openai_api_key": "SECRET_OPENAI",
    }
    public_settings = engine.public_settings()
    checks.append(engine.get_execution_mode() == "manual" or fail("missing execution_mode is not manual"))
    checks.append(
        public_settings.get("execution_mode") == "manual"
        or fail("public_settings missing manual execution_mode")
    )
    checks.append("gemini_api_key" not in public_settings or fail("public_settings exposes gemini_api_key"))
    checks.append("openai_api_key" not in public_settings or fail("public_settings exposes openai_api_key"))
    checks.append("api_key" not in public_settings or fail("public_settings exposes api_key"))
    pass_line("public settings include execution mode without raw API keys")

    engine.settings["execution_mode"] = "one_task"
    public_settings = engine.public_settings()
    checks.append(engine.get_execution_mode() == "one_task" or fail("one_task mode was not returned"))
    checks.append(
        public_settings.get("execution_mode") == "one_task"
        or fail("public_settings missing one_task execution_mode")
    )
    checks.append(
        public_settings.get("automatic_analysis_enabled") is False
        or fail("one_task public settings enables automatic analysis")
    )
    checks.append("gemini_api_key" not in public_settings or fail("one_task public_settings exposes gemini_api_key"))
    checks.append("openai_api_key" not in public_settings or fail("one_task public_settings exposes openai_api_key"))
    checks.append("api_key" not in public_settings or fail("one_task public_settings exposes api_key"))
    pass_line("engine reports one_task mode without automatic analysis or raw API keys")

    engine.settings["execution_mode"] = "one_packet"
    public_settings = engine.public_settings()
    checks.append(engine.get_execution_mode() == "one_packet" or fail("one_packet mode was not returned"))
    checks.append(
        public_settings.get("execution_mode") == "one_packet"
        or fail("public_settings missing one_packet execution_mode")
    )
    checks.append(
        public_settings.get("automatic_analysis_enabled") is False
        or fail("one_packet public settings enables automatic analysis")
    )
    checks.append("gemini_api_key" not in public_settings or fail("one_packet public_settings exposes gemini_api_key"))
    checks.append("openai_api_key" not in public_settings or fail("one_packet public_settings exposes openai_api_key"))
    checks.append("api_key" not in public_settings or fail("one_packet public_settings exposes api_key"))
    pass_line("engine reports one_packet mode without automatic analysis or raw API keys")

    engine.settings["execution_mode"] = "autopilot"
    public_settings = engine.public_settings()
    checks.append(engine.get_execution_mode() == "autopilot" or fail("autopilot mode was not returned"))
    checks.append(
        public_settings.get("execution_mode") == "autopilot"
        or fail("public_settings missing autopilot execution_mode")
    )
    pass_line("engine reports autopilot execution mode")

    dashboard_text = read_text("dashboard.py")
    checks.append('"/api/execution-mode"' in dashboard_text or fail("/api/execution-mode route missing"))
    checks.append(
        "self.engine.get_execution_mode()" in dashboard_text
        or fail("Auto-Pilot start route does not check execution mode")
    )
    checks.append(
        "Auto-Pilot is disabled while execution mode is manual" in dashboard_text
        or fail("manual mode Auto-Pilot guard message missing")
    )
    pass_line("dashboard routes and Auto-Pilot guard are present")

    app_text = read_text("static/js/app.js")
    checks.append('"Copy Codex"' in app_text or fail("Copy Codex button text missing"))
    checks.append('"/api/execution-mode"' in app_text or fail("frontend execution mode API call missing"))
    checks.append(
        "navigator.clipboard.writeText" in app_text
        or fail("clipboard writeText support missing")
    )
    helper_match = re.search(
        r"async\s+copyCodexCommand\s*\([^)]*\)\s*\{(?P<body>.*?)\n    \},",
        app_text,
        re.DOTALL,
    )
    checks.append(helper_match is not None or fail("copyCodexCommand helper missing"))
    if helper_match is not None:
        checks.append(
            "/api/execute-codex" not in helper_match.group("body")
            or fail("copyCodexCommand helper calls /api/execute-codex")
        )
    pass_line("frontend execution mode and Copy Codex clipboard helpers are present")

    if not all(checks):
        return 1

    pass_line("Packet 005 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
