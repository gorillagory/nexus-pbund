import os
import re
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKFLOW_PATH = os.path.join(PROJECT_ROOT, ".github", "workflows", "nexus-preflight.yml")
DOC_PATHS = [
    os.path.join(PROJECT_ROOT, "README.md"),
    os.path.join(PROJECT_ROOT, "docs", "preflight.md"),
    os.path.join(PROJECT_ROOT, ".readme"),
]


def print_pass(message):
    print("PASS: {}".format(message))


def fail(message):
    print("FAIL: {}".format(message))
    return 1


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def contains_trigger(content, trigger):
    return bool(re.search(r"(?m)^\s*{}:\s*$".format(re.escape(trigger)), content))


def workflow_block(content, key):
    match = re.search(r"(?ms)^{}:\s*\n(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)".format(re.escape(key)), content)
    return match.group("body") if match else ""


def trigger_block(content, trigger):
    on_block = workflow_block(content, "on")
    match = re.search(r"(?ms)^\s{{2}}{}:\s*\n(?P<body>.*?)(?=^\s{{2}}[A-Za-z_][A-Za-z0-9_-]*:|\Z)".format(re.escape(trigger)), on_block)
    return match.group("body") if match else ""


def trigger_limited_to_main(content, trigger):
    block = trigger_block(content, trigger)
    return bool(block and re.search(r"(?m)^\s{4}branches:\s*$", block) and re.search(r"(?m)^\s{6}-\s*main\s*$", block))


def run_quick_preflight():
    return subprocess.run(
        [sys.executable, "scripts/nexus_preflight.py", "--quick"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def documentation_mentions_preflight():
    for path in DOC_PATHS:
        if not os.path.exists(path):
            continue
        if "nexus_preflight.py" in read_text(path):
            return True
    return False


def main():
    if not os.path.exists(WORKFLOW_PATH):
        return fail("workflow exists")
    print_pass("workflow exists")

    workflow = read_text(WORKFLOW_PATH)

    if "scripts/nexus_preflight.py --quick --strict-clean" not in workflow:
        return fail("workflow runs quick strict preflight")
    print_pass("workflow runs quick strict preflight")

    if not contains_trigger(workflow, "push"):
        return fail("workflow has push trigger")
    print_pass("workflow has push trigger")

    if not trigger_limited_to_main(workflow, "push"):
        return fail("workflow push trigger is limited to main")
    print_pass("workflow push trigger is limited to main")

    if not contains_trigger(workflow, "pull_request"):
        return fail("workflow has pull_request trigger")
    print_pass("workflow has pull_request trigger")

    if not trigger_limited_to_main(workflow, "pull_request"):
        return fail("workflow pull_request trigger is limited to main")
    print_pass("workflow pull_request trigger is limited to main")

    if re.search(r"(?m)^\s*tags(?:-ignore)?:\s*$", workflow):
        return fail("workflow does not configure tag triggers")
    print_pass("workflow does not configure tag triggers")

    if "actions/setup-python" not in workflow:
        return fail("workflow uses actions/setup-python")
    print_pass("workflow uses actions/setup-python")

    secret_pattern = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,}|api[_ -]?key\s*[:=])")
    if secret_pattern.search(workflow):
        return fail("workflow does not contain API secrets")
    print_pass("workflow does not contain API secrets")

    forbidden_fragments = [
        "/api/tasks/auto-run",
        "/api/tasks/run-one",
        "/api/work-packets/run",
        "/api/execute-codex",
        "execution_mode=autopilot",
        '"execution_mode":"autopilot"',
        "'execution_mode':'autopilot'",
    ]
    for fragment in forbidden_fragments:
        if fragment in workflow:
            return fail("workflow avoids live execution fragment {}".format(fragment))
    print_pass("workflow avoids live execution endpoints")

    if "codex " in workflow.lower() or "codex exec" in workflow.lower():
        return fail("workflow avoids Codex execution")
    print_pass("workflow avoids Codex execution")

    if "shell" + "=True" in workflow:
        return fail("workflow avoids shell true assignment")
    print_pass("workflow avoids shell true assignment")

    if "subprocess." + "Popen" in workflow:
        return fail("workflow avoids subprocess popen")
    print_pass("workflow avoids subprocess popen")

    if not documentation_mentions_preflight():
        return fail("documentation mentions nexus_preflight.py")
    print_pass("documentation mentions nexus_preflight.py")

    quick = run_quick_preflight()
    if quick.returncode != 0:
        print(quick.stdout)
        print(quick.stderr)
        return fail("local quick preflight exits 0")
    print_pass("local quick preflight exits 0")

    if "NEXUS_PREFLIGHT_RESULT=PASS" not in quick.stdout:
        print(quick.stdout)
        return fail("local quick preflight reports PASS")
    print_pass("local quick preflight reports PASS")

    print_pass("Packet 015 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
