import os
import re
import shutil
import subprocess
import sys
import tempfile


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


import engine as engine_module  # noqa: E402
from dashboard import NexusDashboard  # noqa: E402
from engine import NexusEngine  # noqa: E402
from src.services import packet_branch  # noqa: E402


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


def run(command, cwd):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def make_temp_git_repo():
    temp_dir = tempfile.mkdtemp(prefix="nexus_packet_branch_")
    commands = (
        ["git", "init"],
        ["git", "config", "user.email", "packet025@example.invalid"],
        ["git", "config", "user.name", "Packet 025 Test"],
    )
    for command in commands:
        result = run(command, temp_dir)
        if result.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(result.stderr)
    with open(os.path.join(temp_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("packet branch verifier\n")
    for command in (
        ["git", "add", "README.md"],
        ["git", "commit", "-m", "init"],
        ["git", "branch", "-M", "main"],
    ):
        result = run(command, temp_dir)
        if result.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(result.stderr)
    return temp_dir


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
        "docs/WORKFLOW_LOCK.md": ["Branch Per Packet", "git switch -c", "does not commit, merge, push"],
        "docs/SPRINT_PLAN.md": ["Packet 025 Branch Per Packet foundation", "Branch Per Packet rule"],
        "docs/CHAT_HANDOFF.md": ["Branch Per Packet", "Packet 025"],
    }
    for path, phrases in required.items():
        full_path = os.path.join(PROJECT_ROOT, path)
        check(os.path.exists(full_path), "{} exists".format(path))
        content = read_file(path)
        for phrase in phrases:
            check(phrase in content, "{} contains {}".format(path, phrase))


def verify_service_validation():
    branch = packet_branch.build_packet_branch_name("25", "Branch Per Packet")
    check(branch == "factory/packet-025-branch-per-packet", "branch builder pads packet number and slug")
    valid, error = packet_branch.validate_packet_branch_name(branch)
    check(valid and error is None, "valid packet branch passes validation")

    unsafe_names = (
        "main",
        "factory/packet-25-nope",
        "factory/packet-025-bad slug",
        "factory/packet-025-../bad",
        "factory/packet-025-bad.lock",
        "-factory/packet-025-bad",
        "factory/packet-025-bad@{x}",
        "factory/packet-025-bad:ref",
    )
    for name in unsafe_names:
        valid, _ = packet_branch.validate_packet_branch_name(name)
        check(not valid, "rejects unsafe branch {}".format(name))

    try:
        packet_branch.build_packet_branch_name("../25", "bad")
        check(False, "builder rejects unsafe packet number")
    except ValueError:
        check(True, "builder rejects unsafe packet number")

    fake_secret = "sk-" + "packet025secret"
    redacted = packet_branch.redact_git_output("token={}".format(fake_secret))
    check(fake_secret not in redacted, "packet branch output redaction works")


def verify_service_prepare():
    repo = make_temp_git_repo()
    try:
        status = packet_branch.packet_branch_status(repo, packet_number="25", title="Branch Per Packet")
        check(status.get("current_branch") == "main", "temp repo starts on main")
        check(status.get("is_clean") is True, "temp repo starts clean")
        check(status.get("can_prepare") is True, "status allows clean main prepare")

        no_confirm = packet_branch.prepare_packet_branch(repo, "25", "Branch Per Packet", confirm_prepare=False)
        check(no_confirm.get("ok") is False, "prepare requires explicit confirmation")
        check(packet_branch.current_branch(repo)[0] == "main", "no-confirm prepare does not switch")

        prepared = packet_branch.prepare_packet_branch(repo, "25", "Branch Per Packet", confirm_prepare=True)
        check(prepared.get("ok") is True, "prepare succeeds with explicit confirmation")
        check(prepared.get("branch") == "factory/packet-025-branch-per-packet", "prepare returns constructed branch")
        check(packet_branch.current_branch(repo)[0] == "factory/packet-025-branch-per-packet", "prepare switches to packet branch")

        repeat = packet_branch.prepare_packet_branch(repo, "26", "Next Packet", confirm_prepare=True)
        check(repeat.get("ok") is False, "prepare rejects non-main branch")
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    dirty_repo = make_temp_git_repo()
    try:
        with open(os.path.join(dirty_repo, "dirty.txt"), "w", encoding="utf-8") as handle:
            handle.write("dirty")
        result = packet_branch.prepare_packet_branch(dirty_repo, "25", "Dirty Worktree", confirm_prepare=True)
        check(result.get("ok") is False, "prepare rejects dirty worktree")
        check(packet_branch.current_branch(dirty_repo)[0] == "main", "dirty rejection does not switch")
    finally:
        shutil.rmtree(dirty_repo, ignore_errors=True)

    existing_repo = make_temp_git_repo()
    try:
        first = packet_branch.prepare_packet_branch(existing_repo, "25", "Existing Branch", confirm_prepare=True)
        check(first.get("ok") is True, "prepare creates branch for existing-branch test")
        run(["git", "switch", "main"], existing_repo)
        second = packet_branch.prepare_packet_branch(existing_repo, "25", "Existing Branch", confirm_prepare=True)
        check(second.get("ok") is False, "prepare rejects existing target branch")
    finally:
        shutil.rmtree(existing_repo, ignore_errors=True)


def verify_routes():
    client = make_client()
    response = client.get("/api/packet-branch/status?packet_number=25&title=Branch%20Per%20Packet")
    payload = response.get_json(silent=True) or {}
    check(response.status_code == 200, "packet branch status route HTTP 200")
    check(payload.get("status") == "success", "packet branch status route success")
    packet_status = payload.get("packet_branch") or {}
    check(packet_status.get("suggested_branch") == "factory/packet-025-branch-per-packet", "status route returns server-built branch")

    response = client.post(
        "/api/packet-branch/prepare",
        json={"packet_number": "25", "title": "Branch Per Packet"},
    )
    payload = response.get_json(silent=True) or {}
    check(response.status_code == 400, "prepare route without confirmation HTTP 400")
    check(payload.get("status") == "error", "prepare route without confirmation error")

    response = client.post(
        "/api/packet-branch/prepare",
        json={"packet_number": "../25", "title": "bad", "confirm_prepare": True},
    )
    payload = response.get_json(silent=True) or {}
    check(response.status_code == 400, "prepare route rejects unsafe packet number HTTP 400")
    check(payload.get("status") == "error", "prepare route rejects unsafe packet number")


def verify_source_text():
    dashboard = read_file("dashboard.py")
    app_js = read_file("static/js/app.js")
    template = read_file("templates/index.html")
    preflight = read_file("scripts/nexus_preflight.py")
    service = read_file("src/services/packet_branch.py")

    for marker in ("/api/packet-branch/status", "/api/packet-branch/prepare"):
        check(marker in dashboard, "dashboard contains {}".format(marker))

    for marker in (
        "Branch Per Packet",
        "packet-branch-number",
        "packet-branch-title",
        "preparePacketBranch",
        "NexusCore.confirmAction",
    ):
        check(marker in app_js + template, "frontend contains {}".format(marker))

    check("src/services/packet_branch.py" in preflight, "preflight py_compile includes packet branch service")
    check("validate_packet_branch_name" in service, "service contains branch validation")
    check("confirm_prepare is not True" in service, "service requires explicit confirmation")
    check("get_status(repo_dir)" in service, "service checks worktree status")
    check('branch != "main"' in service, "service checks main branch before creation")
    check('["switch", "-c", branch_name]' in service, "service contains only allowed switch create command")
    check("redact_git_output" in service and "bounded_output" in service, "service redacts and bounds output")
    check("subprocess.run" in service, "service uses subprocess.run")
    check("shell=True" not in service + dashboard, "packet branch avoids shell=True")
    check("subprocess." + "Popen" not in service + dashboard, "packet branch avoids subprocess.Popen")

    unsafe_fragments = (
        '["add"',
        '["commit"',
        '["merge"',
        '["checkout"',
        '["push"',
        '["pull"',
        '["fetch"',
        '["reset"',
        '["clean"',
        '["rebase"',
        '["stash"',
        '["tag"',
        '["branch", "-d"',
        '["branch", "-D"',
    )
    for fragment in unsafe_fragments:
        check(fragment not in service, "packet branch service avoids {}".format(fragment))

    route_section = section_between(dashboard, "/api/packet-branch/status", "/api/factory/ci-status")
    blocked_routes = (
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
    )
    for route in blocked_routes:
        check(route not in route_section, "packet branch routes avoid {}".format(route))
    check("execution_mode" not in route_section, "packet branch routes do not set execution mode")
    check("set_execution_mode" not in route_section, "packet branch routes do not call set_execution_mode")

    ui_section = section_between(template, "packet-branch-panel", "/api/git-explorer/summary")
    app_section = section_between(app_js, "packetBranchFormData", "renderFactoryEvents")
    check("alert(" not in app_section, "packet branch frontend avoids native alert")
    check("confirm(" not in app_section, "packet branch frontend avoids native confirm")
    button_text = " ".join(re.findall(r"<button\b[^>]*>(.*?)</button>", ui_section, flags=re.DOTALL | re.IGNORECASE))
    button_text = re.sub(r"<[^>]+>", " ", button_text)
    for label in ("Commit", "Merge", "Push", "Tag", "Reset", "Clean", "Rebase", "Stash", "Delete"):
        check(label.lower() not in button_text.lower(), "packet branch UI has no {} button".format(label))

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
    verify_service_validation()
    verify_service_prepare()
    verify_routes()
    verify_source_text()
    verify_node_check()
    if FAILURES:
        print("FAIL: Packet 025 verification failed")
        return 1
    print("PASS: Packet 025 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
