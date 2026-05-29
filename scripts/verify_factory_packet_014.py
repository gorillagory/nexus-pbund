import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PREFLIGHT_PATH = os.path.join(PROJECT_ROOT, "scripts", "nexus_preflight.py")


def print_pass(message):
    print("PASS: {}".format(message))


def fail(message):
    print("FAIL: {}".format(message))
    return 1


def run_preflight(args):
    return subprocess.run(
        [sys.executable, PREFLIGHT_PATH] + list(args),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def extract_json_summary(output):
    start = output.rfind("\n{")
    if start == -1:
        start = output.find("{")
    if start == -1:
        return None
    try:
        return json.loads(output[start:].strip())
    except (TypeError, ValueError):
        return None


def main():
    if not os.path.exists(PREFLIGHT_PATH):
        return fail("scripts/nexus_preflight.py exists")
    print_pass("scripts/nexus_preflight.py exists")

    with open(PREFLIGHT_PATH, "r", encoding="utf-8") as handle:
        content = handle.read()

    if "shell" + "=True" in content:
        return fail("preflight contains shell true assignment")
    print_pass("preflight avoids shell true assignment")

    if "subprocess." + "Popen" in content:
        return fail("preflight contains subprocess popen")
    print_pass("preflight avoids subprocess popen")

    quick = run_preflight(["--quick"])
    if quick.returncode != 0:
        print(quick.stdout)
        print(quick.stderr)
        return fail("nexus_preflight.py --quick exits 0")
    print_pass("nexus_preflight.py --quick exits 0")

    if "NEXUS_PREFLIGHT_RESULT=PASS" not in quick.stdout:
        print(quick.stdout)
        return fail("quick preflight reports PASS")
    print_pass("quick preflight reports PASS")

    quick_json = run_preflight(["--quick", "--json"])
    if quick_json.returncode != 0:
        print(quick_json.stdout)
        print(quick_json.stderr)
        return fail("nexus_preflight.py --quick --json exits 0")
    print_pass("nexus_preflight.py --quick --json exits 0")

    summary = extract_json_summary(quick_json.stdout)
    if summary is None:
        return fail("json summary is present")
    print_pass("json summary is present")

    if summary.get("result") != "PASS":
        return fail("json summary reports PASS")
    print_pass("json summary reports PASS")

    print_pass("Packet 014 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
