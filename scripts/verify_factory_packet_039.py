import ast
import os
import re
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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


def parse_python(relative_path):
    return ast.parse(read_file(relative_path), filename=relative_path)


def iter_python_files(relative_roots):
    for relative_root in relative_roots:
        full_root = os.path.join(PROJECT_ROOT, relative_root)
        if os.path.isfile(full_root):
            yield relative_root
            continue
        for root, dirs, files in os.walk(full_root):
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            ]
            for file_name in files:
                if file_name.endswith(".py"):
                    yield os.path.relpath(os.path.join(root, file_name), PROJECT_ROOT)


def find_ast_calls(relative_path, attribute_name):
    tree = parse_python(relative_path)
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == attribute_name:
            matches.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == attribute_name:
            matches.append(node.lineno)
    return matches


def has_shell_true(relative_path):
    tree = parse_python(relative_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return True
    return False


def verify_runner_static():
    path = "scripts/nexus_codex_job.py"
    full_path = os.path.join(PROJECT_ROOT, path)
    check(os.path.exists(full_path), "Codex job runner script exists")
    source = read_file(path)

    for phrase in (
        "JOB_ROOT = Path(\"/tmp/nexus-codex-jobs\")",
        "def validate_job_name",
        "JOB_NAME_PATTERN",
        "^[A-Za-z0-9_-]{1,60}$",
        "def validate_prompt_file",
        "prompt_path.is_file()",
        "MAX_PROMPT_BYTES",
        "subprocess.Popen(",
        "start_new_session=True",
        "shell=True",
    ):
        expected = phrase != "shell=True"
        check((phrase in source) is expected, "runner static expectation for {}".format(phrase))

    for command in ("start", "status", "tail", "list", "stop"):
        check("add_parser(\"{}\"".format(command) in source, "runner supports {} command".format(command))

    for phrase in (
        "stdin=subprocess.DEVNULL",
        "stderr=subprocess.STDOUT",
        "combined.log",
        "runner.log",
        "status.json",
        "report_expected",
        "expected_report_path",
        "SECRET_TEXT_PATTERN",
        "bounded_text",
        "verify_managed_process",
        "os.killpg",
        "No combined log exists yet",
    ):
        check(phrase in source, "runner contains {}".format(phrase))

    forbidden = (
        "@app.route",
        "Flask(",
        "/api/",
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "discord.py",
        "set_execution_mode",
        "git push",
        "git reset",
        "git clean",
    )
    for phrase in forbidden:
        check(phrase not in source, "runner does not contain {}".format(phrase))


def verify_runner_behavior_surface():
    result = subprocess.run(
        [sys.executable, "scripts/nexus_codex_job.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    check(result.returncode == 0, "runner --help exits successfully")
    for phrase in ("start", "status", "tail", "list", "stop", "/tmp/nexus-codex-jobs"):
        check(phrase in result.stdout, "runner help mentions {}".format(phrase))

    bad_name = subprocess.run(
        [
            sys.executable,
            "scripts/nexus_codex_job.py",
            "start",
            "--name",
            "../bad",
            "--prompt-file",
            "missing.txt",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    check(bad_name.returncode != 0, "unsafe job name is rejected")
    check("Job name must use only" in bad_name.stderr, "unsafe job name rejection is explicit")


def verify_popen_and_shell_safety():
    popen_matches = {}
    for relative_path in iter_python_files(["dashboard.py", "src/services", "scripts/nexus_codex_job.py"]):
        matches = find_ast_calls(relative_path, "Popen")
        if matches:
            popen_matches[relative_path] = matches

    check(
        set(popen_matches.keys()) == {"scripts/nexus_codex_job.py"},
        "subprocess.Popen AST usage is isolated to scripts/nexus_codex_job.py",
    )
    check(
        not find_ast_calls("dashboard.py", "Popen"),
        "dashboard.py still does not use subprocess.Popen",
    )
    services_popen = []
    for relative_path in iter_python_files(["src/services"]):
        if find_ast_calls(relative_path, "Popen"):
            services_popen.append(relative_path)
    check(not services_popen, "src/services still do not use subprocess.Popen")

    shell_true = []
    for relative_path in iter_python_files(["dashboard.py", "engine.py", "src", "scripts/nexus_codex_job.py"]):
        if has_shell_true(relative_path):
            shell_true.append(relative_path)
    check(not shell_true, "no shell=True AST calls in dashboard.py engine.py src or job runner")


def verify_docs():
    operator = read_file("docs/OPERATOR_RUNBOOK.md")
    workflow = read_file("docs/WORKFLOW_LOCK.md")
    combined = operator + "\n" + workflow

    for phrase in (
        "Server-Side Codex Job Runner",
        "scripts/nexus_codex_job.py start --name",
        "scripts/nexus_codex_job.py status --job-id",
        "scripts/nexus_codex_job.py tail --job-id",
        "/tmp/nexus-codex-jobs",
        "tmux",
        "disconnect",
        "Do not run long Codex jobs in raw phone SSH foreground",
        "No Auto-Pilot",
        "Discord remains capture-only",
    ):
        check(phrase in combined, "docs mention {}".format(phrase))

    for phrase in (
        "Auto-Pilot is enabled",
        "Auto-Pilot unlocked",
        "Discord can execute",
        "Git Explorer can write",
        "force push as normal",
    ):
        check(phrase not in combined, "docs do not claim unsafe behavior: {}".format(phrase))

    secret_patterns = (
        r"https://discord(?:app)?\.com/api/webhooks/[A-Za-z0-9/_-]{20,}",
        r"sk-[A-Za-z0-9_-]{8,}",
        r"AIza[0-9A-Za-z_-]{20,}",
        r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9][A-Za-z0-9._~+/=-]{23,}",
    )
    for pattern in secret_patterns:
        check(re.search(pattern, combined, flags=re.IGNORECASE) is None, "docs do not expose raw secret pattern {}".format(pattern))


def verify_no_app_api_execution_expansion():
    scanned = "\n".join(
        read_file(path)
        for path in (
            "dashboard.py",
            "static/js/app.js",
            "static/js/chat.js",
            "templates/index.html",
        )
    )
    check("nexus_codex_job.py" not in scanned, "job runner is not wired into app/API/frontend")
    check("codex job runner" not in scanned.lower(), "app/API/frontend do not expose Codex job runner controls")

    unsafe_unlocks = (
        "Auto-Pilot is enabled",
        "Auto-Pilot unlocked",
        "discord command execution",
        "Discord can execute",
    )
    for phrase in unsafe_unlocks:
        check(phrase not in scanned, "app/API/frontend do not claim {}".format(phrase))


def verify_preflight_discovery():
    import scripts.nexus_preflight as preflight

    discovered = preflight.discover_packet_verifiers()
    check("scripts/verify_factory_packet_039.py" in discovered.get(39, []), "packet 039 verifier is discoverable")


def main():
    verify_runner_static()
    verify_runner_behavior_surface()
    verify_popen_and_shell_safety()
    verify_docs()
    verify_no_app_api_execution_expansion()
    verify_preflight_discovery()
    if FAILURES:
        print("FAIL: Packet 039 verification failed")
        return 1
    print("PASS: Packet 039 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
