import os
import shutil
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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


def section_between(content, start, end):
    start_index = content.find(start)
    if start_index == -1:
        return ""
    end_index = content.find(end, start_index + len(start))
    if end_index == -1:
        return content[start_index:]
    return content[start_index:end_index]


def run_command(command):
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def verify_source_markers():
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    style = read_file("static/style.css")
    combined_ui = template + "\n" + app_js

    for marker in (
        "renderFactoryConsole",
        "loadFactoryConsole",
        "escapeHtml",
        "Recent Events",
        "Recent Execution Runs",
        "Git Changes",
        "Preflight / CI Status",
        "Safe Next Actions",
    ):
        check(marker in combined_ui, "UI/source contains {}".format(marker))

    for marker in (
        "Factory Run Console",
        "Factory Summary",
        "Recent Events",
        "Recent Execution Runs",
    ):
        check(marker in combined_ui, "template/source contains {}".format(marker))

    for marker in (
        "factory-summary-card",
        "factory-console-panel",
        "factory-event-timeline",
        "factory-status-badge",
        "factory-runs-table",
        "factory-preflight-output",
    ):
        check(marker in style, "style contains {}".format(marker))


def verify_factory_console_safety():
    app_js = read_file("static/js/app.js")
    load_section = section_between(app_js, "async loadFactoryConsole()", "startFactoryConsolePolling()")
    render_section = section_between(app_js, "renderFactoryConsole(data)", "async loadFactoryPreflightStatus()")
    factory_console_section = load_section + "\n" + render_section
    forbidden = [
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    ]
    for fragment in forbidden:
        check(fragment not in factory_console_section, "factory console render/refresh avoids {}".format(fragment))

    check("alert(" not in factory_console_section, "factory console render/refresh avoids alert")
    check("confirm(" not in factory_console_section, "factory console render/refresh avoids confirm")
    check("data.gemini_api_key" not in app_js, "frontend avoids raw Gemini API key reads")
    check("data.openai_api_key" not in app_js, "frontend avoids raw OpenAI API key reads")
    check("data.api_key" not in app_js, "frontend avoids raw generic API key reads")


def verify_node_check():
    if shutil.which("node") is None:
        print("PASS: node --check skipped because node is unavailable")
        return
    result = run_command(["node", "--check", "static/js/app.js"])
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    check(result.returncode == 0, "node --check static/js/app.js")


def verify_quick_preflight():
    result = run_command([sys.executable, "scripts/nexus_preflight.py", "--quick"])
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    check(result.returncode == 0, "nexus_preflight.py --quick exits 0")
    check("NEXUS_PREFLIGHT_RESULT=PASS" in result.stdout, "nexus_preflight.py --quick reports PASS")


def main():
    verify_source_markers()
    verify_factory_console_safety()
    verify_node_check()
    verify_quick_preflight()
    check("shell" + "=True" not in read_file("static/js/app.js"), "frontend avoids shell true text")
    check("subprocess." + "Popen" not in read_file("static/js/app.js"), "frontend avoids subprocess popen text")
    if FAILURES:
        print("FAIL: Packet 017 verification failed")
        return 1
    print("PASS: Packet 017 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
