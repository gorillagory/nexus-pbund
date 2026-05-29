import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SUITE_PATH = os.path.join(PROJECT_ROOT, "scripts", "verify_factory_regression_suite.py")


def main():
    result = subprocess.run(
        [sys.executable, SUITE_PATH],
        cwd=PROJECT_ROOT,
        shell=False,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    print("PASS: Packet 013 verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
