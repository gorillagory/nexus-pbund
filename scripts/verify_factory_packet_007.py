import json
import os
import re
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


SAMPLE_PACKET = """# Packet 999 \u2014 Sample

Risk: low
Stop condition: stop after first failure
Estimated minutes: 15

Task 1 \u2014 Create file
codex "Create sample_file.py with a harmless hello function. Do not run anything."

Task 2 \u2014 Patch file
codex "Patch sample_file.py to add a docstring. Do not run anything."
"""


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


def main():
    checks = []

    from src.services.work_packet_parser import extract_codex_commands, parse_work_packet

    packet = parse_work_packet(SAMPLE_PACKET)
    commands = extract_codex_commands(SAMPLE_PACKET)
    checks.append(packet.get("title") == "Packet 999 \u2014 Sample" or fail("packet title parse failed"))
    checks.append(packet.get("risk_level") == "low" or fail("risk level parse failed"))
    checks.append("first failure" in packet.get("stop_condition", "") or fail("stop condition parse failed"))
    checks.append("15" in packet.get("estimated_minutes", "") or fail("estimated minutes parse failed"))
    checks.append(len(packet.get("tasks", [])) == 2 or fail("task parse count failed"))
    checks.append(len(commands) == 2 or fail("codex command count failed"))
    checks.append(
        all("```bash" in task.get("description", "") for task in packet.get("tasks", []))
        or fail("task descriptions do not contain fenced codex command blocks")
    )
    checks.append(commands[0].startswith('codex "') or fail("first codex command prefix failed"))
    pass_line("parser extracts packet metadata and codex tasks")

    import engine as engine_module
    from dashboard import NexusDashboard
    from engine import NexusEngine

    class DummyChatSessionStore:
        def __init__(self, max_messages=20):
            self.max_messages = max_messages

    engine_module.ChatSessionStore = DummyChatSessionStore
    engine = NexusEngine(os.getcwd())
    dashboard = NexusDashboard(engine)
    client = dashboard.app.test_client()

    response = client.post(
        "/api/work-packets/preview",
        json={"packet_text": SAMPLE_PACKET},
    )
    response_data = response.get_json()
    checks.append(response.status_code == 200 or fail("preview route did not return HTTP 200"))
    checks.append(response_data.get("status") == "success" or fail("preview route status failed"))
    checks.append(response_data.get("task_count") == 2 or fail("preview route task_count failed"))
    dumped_response = json.dumps(response_data, sort_keys=True)
    for secret_field in ("gemini_api_key", "openai_api_key", "api_key"):
        checks.append(secret_field not in dumped_response or fail("preview response exposes {}".format(secret_field)))
    pass_line("preview route returns safe packet response")

    empty_response = client.post(
        "/api/work-packets/preview",
        json={"packet_text": ""},
    )
    checks.append(empty_response.status_code == 400 or fail("empty preview route did not return HTTP 400"))
    pass_line("preview route rejects empty packet_text")

    dashboard_text = read_text("dashboard.py")
    checks.append('"/api/work-packets/preview"' in dashboard_text or fail("preview route missing"))
    checks.append('"/api/work-packets/stage"' in dashboard_text or fail("stage route missing"))
    preview_body = route_body(dashboard_text, "/api/work-packets/preview")
    stage_body = route_body(dashboard_text, "/api/work-packets/stage")
    route_sections = preview_body + "\n" + stage_body
    checks.append("execute-codex" not in route_sections or fail("work packet routes reference execute-codex"))
    checks.append("CodexRunner" not in route_sections or fail("work packet routes instantiate CodexRunner"))
    pass_line("work packet backend routes avoid Codex execution paths")

    app_text = read_text("static/js/app.js")
    template_text = read_text("templates/index.html")
    ui_text = app_text + "\n" + template_text
    checks.append("Work Packet Manager" in ui_text or fail("Work Packet Manager UI missing"))
    checks.append("/api/work-packets/preview" in ui_text or fail("preview endpoint missing from frontend"))
    checks.append("/api/work-packets/stage" in ui_text or fail("stage endpoint missing from frontend"))
    checks.append("Copy All Codex Commands" in ui_text or fail("copy all command UI missing"))
    checks.append(
        "Manual Mode: staging and copying only" in ui_text
        or fail("manual mode work packet warning missing")
    )
    work_packet_js = app_text[app_text.find("previewWorkPacket") :]
    checks.append(
        '"/api/execute-codex"' not in work_packet_js
        and "'/api/execute-codex'" not in work_packet_js
        or fail("work packet UI calls execute-codex")
    )
    pass_line("frontend work packet UI is present and non-executing")

    if not all(checks):
        return 1

    pass_line("Packet 007 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
