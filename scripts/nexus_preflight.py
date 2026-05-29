import argparse
import json
import os
import re
import shutil
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PY_COMPILE_FILES = [
    "engine.py",
    "dashboard.py",
    "models.py",
    "database.py",
    "bundle.py",
    "ai_clients/base.py",
    "ai_clients/factory.py",
    "ai_clients/gemini_client.py",
    "ai_clients/openai_client.py",
    "model_registry.py",
    "task_router.py",
    "chat_session_store.py",
    "src/services/codex_runner.py",
    "src/services/cost_ledger.py",
    "src/services/discord_router.py",
    "src/services/work_packet_parser.py",
    "src/services/factory_events.py",
    "src/services/git_changes.py",
    "src/services/git_explorer.py",
    "src/services/orchestration_inbox.py",
    "src/services/prompt_vault.py",
]

VERIFY_SCRIPTS = [
    "scripts/verify_watchdog_ignores.py",
    "scripts/verify_factory_packet_002_003_004.py",
    "scripts/verify_factory_packet_005.py",
    "scripts/verify_factory_packet_006.py",
    "scripts/verify_factory_packet_007.py",
    "scripts/verify_factory_packet_008.py",
    "scripts/verify_factory_packet_009.py",
    "scripts/verify_factory_execution_console.py",
    "scripts/verify_factory_schema_sync.py",
    "scripts/verify_factory_packet_011.py",
    "scripts/verify_factory_packet_012.py",
    "scripts/verify_factory_regression_suite.py",
    "scripts/verify_factory_packet_013.py",
]

QUICK_VERIFY_SCRIPTS = [
    "scripts/verify_factory_regression_suite.py",
    "scripts/verify_factory_packet_013.py",
]


def run_command(command, label):
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "label": label,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }


def print_section(title):
    print("\n== {} ==".format(title))


def print_result(status, label, detail=None):
    line = "{}: {}".format(status, label)
    if detail:
        line = "{} - {}".format(line, detail)
    print(line)


def existing_paths(paths):
    return [path for path in paths if os.path.exists(os.path.join(PROJECT_ROOT, path))]


def git_status_short():
    result = run_command(["git", "status", "--short"], "git status --short")
    return result, result["stdout"].strip()


def iter_files(paths, suffixes):
    for rel_path in paths:
        full_path = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.isfile(full_path):
            if full_path.endswith(suffixes):
                yield full_path
            continue
        if not os.path.isdir(full_path):
            continue
        for root, dirs, files in os.walk(full_path):
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in {
                    ".git",
                    ".nexus",
                    ".codex",
                    "__pycache__",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                    "node_modules",
                    "venv",
                    ".venv",
                    ".postgres-data",
                }
            ]
            for file_name in files:
                full_file = os.path.join(root, file_name)
                if full_file.endswith(suffixes):
                    yield full_file


def contains_text(file_path, needle):
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return needle in handle.read()
    except OSError:
        return False


def run_safety_scans(summary):
    print_section("Safety Scans")
    failed = False
    shell_assignment = "shell" + "=True"
    popen_name = "subprocess." + "Popen"
    raw_key_pattern = re.compile(r"data\.(gemini_api_key|openai_api_key|api_key|discord_ingest_secret)([^_A-Za-z0-9]|$)")

    checks = [
        (
            "no shell true assignment in Python safety surface",
            list(iter_files(["dashboard.py", "engine.py", "src"], (".py",))),
            lambda path: contains_text(path, shell_assignment),
        ),
        (
            "no subprocess popen in dashboard/services",
            list(iter_files(["dashboard.py", "src/services"], (".py",))),
            lambda path: contains_text(path, popen_name),
        ),
        (
            "no raw settings return",
            list(iter_files(["dashboard.py", "engine.py"], (".py",))),
            lambda path: contains_text(path, "return self.engine.settings"),
        ),
        (
            "no frontend raw API key reads",
            list(iter_files(["static/js"], (".js",))),
            lambda path: bool(raw_key_pattern.search(open(path, "r", encoding="utf-8").read())),
        ),
    ]

    for label, files, matcher in checks:
        matches = []
        for file_path in files:
            try:
                if matcher(file_path):
                    matches.append(os.path.relpath(file_path, PROJECT_ROOT))
            except OSError:
                matches.append(os.path.relpath(file_path, PROJECT_ROOT))
        if matches:
            failed = True
            print_result("FAIL", label, ", ".join(matches))
            summary["checks"].append({"name": label, "status": "FAIL", "details": matches})
        else:
            print_result("PASS", label)
            summary["checks"].append({"name": label, "status": "PASS", "details": []})

    return not failed


def run_py_compile(summary):
    print_section("Python Compile")
    files = existing_paths(PY_COMPILE_FILES)
    if not files:
        print_result("SKIP", "py_compile", "no files found")
        summary["checks"].append({"name": "py_compile", "status": "SKIP"})
        return True

    result = run_command([sys.executable, "-m", "py_compile"] + files, "py_compile")
    if result["returncode"] == 0:
        print_result("PASS", "py_compile", "{} files".format(len(files)))
        summary["checks"].append({"name": "py_compile", "status": "PASS"})
        return True

    print_result("FAIL", "py_compile")
    if result["stdout"].strip():
        print(result["stdout"].rstrip())
    if result["stderr"].strip():
        print(result["stderr"].rstrip())
    summary["checks"].append({"name": "py_compile", "status": "FAIL"})
    return False


def run_verification_scripts(summary, quick=False):
    print_section("Verification Scripts")
    scripts = QUICK_VERIFY_SCRIPTS if quick else VERIFY_SCRIPTS
    ok = True
    for script in scripts:
        if not os.path.exists(os.path.join(PROJECT_ROOT, script)):
            print_result("SKIP", script, "missing")
            summary["checks"].append({"name": script, "status": "SKIP"})
            continue
        result = run_command([sys.executable, script], script)
        if result["returncode"] == 0:
            print_result("PASS", script)
            summary["checks"].append({"name": script, "status": "PASS"})
            continue
        ok = False
        print_result("FAIL", script, "exit {}".format(result["returncode"]))
        if result["stdout"].strip():
            print(result["stdout"].rstrip())
        if result["stderr"].strip():
            print(result["stderr"].rstrip())
        summary["checks"].append({"name": script, "status": "FAIL"})
    return ok


def run_node_check(summary):
    print_section("Node Syntax")
    app_js = os.path.join(PROJECT_ROOT, "static/js/app.js")
    if not os.path.exists(app_js):
        print_result("SKIP", "node --check static/js/app.js", "missing app.js")
        summary["checks"].append({"name": "node --check static/js/app.js", "status": "SKIP"})
        return True
    if shutil.which("node") is None:
        print_result("SKIP", "node --check static/js/app.js", "node missing")
        summary["checks"].append({"name": "node --check static/js/app.js", "status": "SKIP"})
        return True

    result = run_command(["node", "--check", "static/js/app.js"], "node --check static/js/app.js")
    if result["returncode"] == 0:
        print_result("PASS", "node --check static/js/app.js")
        summary["checks"].append({"name": "node --check static/js/app.js", "status": "PASS"})
        return True

    print_result("FAIL", "node --check static/js/app.js")
    if result["stdout"].strip():
        print(result["stdout"].rstrip())
    if result["stderr"].strip():
        print(result["stderr"].rstrip())
    summary["checks"].append({"name": "node --check static/js/app.js", "status": "FAIL"})
    return False


def main():
    parser = argparse.ArgumentParser(description="Run local Nexus no-token preflight checks.")
    parser.add_argument("--strict-clean", action="store_true", help="Fail if the repo is dirty before checks.")
    parser.add_argument("--quick", action="store_true", help="Run the fast no-token safety subset.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary after text output.")
    args = parser.parse_args()

    summary = {
        "result": "PASS",
        "strict_clean": args.strict_clean,
        "quick": args.quick,
        "checks": [],
    }

    print("Nexus Local Preflight")
    initial_result, initial_status = git_status_short()
    if initial_result["returncode"] != 0:
        print_result("FAIL", "initial git status", initial_result["stderr"].strip())
        summary["checks"].append({"name": "initial git status", "status": "FAIL"})
        summary["result"] = "FAIL"
    elif initial_status:
        status = "FAIL" if args.strict_clean else "WARN"
        print_result(status, "repo dirty before checks", initial_status.replace("\n", "; "))
        summary["checks"].append({"name": "repo clean before checks", "status": status, "details": initial_status})
        if args.strict_clean:
            summary["result"] = "FAIL"
    else:
        print_result("PASS", "repo clean before checks")
        summary["checks"].append({"name": "repo clean before checks", "status": "PASS"})

    required_results = [
        run_py_compile(summary),
        run_verification_scripts(summary, quick=args.quick),
        run_safety_scans(summary),
        run_node_check(summary),
    ]

    final_result, final_status = git_status_short()
    print_section("Final Git Status")
    if final_result["returncode"] != 0:
        print_result("FAIL", "final git status", final_result["stderr"].strip())
        summary["checks"].append({"name": "final git status", "status": "FAIL"})
        required_results.append(False)
    elif final_status != initial_status:
        print_result("FAIL", "git status changed during preflight", final_status.replace("\n", "; "))
        summary["checks"].append(
            {
                "name": "git status unchanged",
                "status": "FAIL",
                "before": initial_status,
                "after": final_status,
            }
        )
        required_results.append(False)
    else:
        detail = "clean" if not final_status else final_status.replace("\n", "; ")
        print_result("PASS", "git status unchanged", detail)
        summary["checks"].append({"name": "git status unchanged", "status": "PASS"})

    if not all(required_results):
        summary["result"] = "FAIL"

    print("\nNEXUS_PREFLIGHT_RESULT={}".format(summary["result"]))
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
