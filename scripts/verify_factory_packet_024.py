import os
import re
import shutil
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import engine as engine_module  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from engine import NexusEngine  # noqa: E402
from src.services import git_explorer  # noqa: E402


FAILURES = []


class NoopChatSessionStore:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages

    def get_history(self, session_id):
        return []

    def append_exchange(self, session_id, user_message, assistant_message):
        return None


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


def make_client():
    original_chat_store = engine_module.ChatSessionStore
    engine_module.ChatSessionStore = NoopChatSessionStore
    engine = NexusEngine(PROJECT_ROOT)
    dashboard = NexusDashboard(engine)
    dashboard.app.config["TESTING"] = True
    engine_module.ChatSessionStore = original_chat_store
    return dashboard.app.test_client()


def verify_docs():
    required = {
        "docs/WORKFLOW_LOCK.md": ["Git Explorer", "read-only", "Branch Per Packet remains Packet 025"],
        "docs/SPRINT_PLAN.md": ["Packet 024 Git Explorer foundation", "Git Explorer rule", "Branch Per Packet remains Packet 025"],
        "docs/CHAT_HANDOFF.md": ["Git Explorer", "Packet 024"],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_service():
    check(callable(git_explorer.run_read_only_git), "git explorer has run_read_only_git")
    check(callable(git_explorer.redact_git_output), "git explorer has redaction helper")
    check(callable(git_explorer.get_git_explorer_summary), "git explorer has summary helper")
    check(callable(git_explorer.get_diff_preview), "git explorer has diff preview helper")

    fake_secret = "sk-" + "packet024secret"
    redacted = git_explorer.redact_git_output("token={}\npassword=hunter2".format(fake_secret))
    check(fake_secret not in redacted, "redaction removes secret-looking token")
    check("hunter2" not in redacted, "redaction removes password value")

    result = git_explorer.run_read_only_git(PROJECT_ROOT, ["branch", "--show-current"])
    check(isinstance(result, dict), "read-only git command returns dict")
    check(result.get("returncode") == 0, "read-only git branch command succeeds")

    summary = git_explorer.get_git_explorer_summary(PROJECT_ROOT)
    check("branch" in summary, "summary includes branch")
    check("recent_commits" in summary, "summary includes recent commits")
    check("recent_baseline_tags" in summary, "summary includes baseline tags")
    check("changed_files" in summary, "summary includes changed files")


def verify_routes():
    client = make_client()
    endpoints = (
        "/api/git-explorer/summary",
        "/api/git-explorer/log",
        "/api/git-explorer/tags",
        "/api/git-explorer/changes",
        "/api/git-explorer/diff",
    )
    for endpoint in endpoints:
        response = client.get(endpoint)
        payload = response.get_json(silent=True) or {}
        check(response.status_code == 200, "{} HTTP 200".format(endpoint))
        check(payload.get("status") == "success", "{} returns success".format(endpoint))
        check(len(response.get_data(as_text=True)) < 50000, "{} response is bounded".format(endpoint))

    summary = client.get("/api/git-explorer/summary").get_json(silent=True) or {}
    git = summary.get("git") or {}
    check("branch" in git, "summary route returns branch")
    check("recent_commits" in git, "summary route returns recent commits")
    check("recent_baseline_tags" in git, "summary route returns baseline tags")

    diff = client.get("/api/git-explorer/diff?limit=800").get_json(silent=True) or {}
    preview = diff.get("diff") or {}
    check(preview.get("max_chars") == 800, "diff route honors bounded limit")
    check(len(preview.get("diff") or "") < 1200, "diff route returns bounded preview")


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    style = read_file("static/style.css")
    preflight = read_file("scripts/nexus_preflight.py")
    service = read_file("src/services/git_explorer.py")

    for marker in (
        "/api/git-explorer/summary",
        "/api/git-explorer/log",
        "/api/git-explorer/tags",
        "/api/git-explorer/changes",
        "/api/git-explorer/diff",
    ):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in (
        "Git Explorer",
        "git-explorer-status",
        "git-explorer-diff-preview",
        "loadGitExplorerDiff",
    ):
        check(marker in app_js + template, "frontend contains {}".format(marker))

    check("src/services/git_explorer.py" in preflight, "preflight py_compile includes git explorer service")
    check("git-explorer-line" in style, "style contains Git Explorer list class")
    check("redact_git_output" in service, "service contains redaction helper")
    check("bounded_output" in service, "service bounds git output")
    check("subprocess.run" in service, "service uses subprocess.run")
    check("shell=True" not in service + dashboard, "Git Explorer avoids shell=True")
    check("subprocess." + "Popen" not in service + dashboard, "Git Explorer avoids subprocess.Popen")

    write_fragments = (
        '["add"',
        '["commit"',
        '["merge"',
        '["checkout"',
        '["switch"',
        '["push"',
        '["pull"',
        '["fetch"',
        '["reset"',
        '["clean"',
        '["rebase"',
        '["stash"',
    )
    for fragment in write_fragments:
        check(fragment not in service, "Git Explorer service avoids {}".format(fragment))

    route_section = section_between(dashboard, "/api/git-explorer/summary", "/api/factory/ci-status")
    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in route_section, "Git Explorer routes avoid {}".format(route))

    check("execution_mode" not in route_section, "Git Explorer routes do not set execution mode")
    check("set_execution_mode" not in route_section, "Git Explorer routes do not call set_execution_mode")

    ui_section = section_between(template, "view-git-explorer", "view-orchestration-inbox")
    app_section = section_between(app_js, "async loadGitExplorer", "renderFactoryEvents")
    check("alert(" not in app_section, "Git Explorer frontend avoids native alert")
    check("confirm(" not in app_section, "Git Explorer frontend avoids native confirm")
    button_text = " ".join(re.findall(r"<button\b[^>]*>(.*?)</button>", ui_section, flags=re.DOTALL | re.IGNORECASE))
    button_text = re.sub(r"<[^>]+>", " ", button_text)
    for label in ("Commit", "Merge", "Push", "Tag", "Reset", "Clean"):
        check(label.lower() not in button_text.lower(), "Git Explorer UI has no {} button".format(label))

    raw_secret_pattern = re.compile(r"data\.(discord_ingest_secret|gemini_api_key|openai_api_key|api_key)([^_A-Za-z0-9]|$)")
    check(not raw_secret_pattern.search(app_js), "frontend avoids raw secret reads")


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
    verify_docs()
    verify_service()
    verify_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 024 verification failed")
        return 1
    print("PASS: Packet 024 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
