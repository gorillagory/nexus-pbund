import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import engine as engine_module  # noqa: E402
from engine import NexusEngine, NexusWatcher  # noqa: E402


class NoopChatSessionStore:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages


def print_check(label, passed):
    print("{} {}".format("PASS" if passed else "FAIL", label))


def main():
    workspace_root = os.getcwd()
    engine_module.ChatSessionStore = NoopChatSessionStore
    engine = NexusEngine(workspace_root)
    watcher = NexusWatcher(engine)

    ignored_paths = [
        ".nexus/codex_telemetry.jsonl",
        ".git/index",
        "output/test.txt",
        "context/test.md",
        "node_modules/pkg/index.js",
        "venv/lib/test.py",
        ".postgres-data/file",
    ]

    all_passed = True
    for rel_path in ignored_paths:
        full_path = os.path.join(workspace_root, *rel_path.split("/"))
        ignored = watcher._should_ignore(full_path)
        print_check("{} is ignored".format(rel_path), ignored)
        all_passed = all_passed and ignored

    engine_path = os.path.join(workspace_root, "engine.py")
    engine_is_not_ignored = not watcher._should_ignore(engine_path)
    print_check("engine.py is not ignored", engine_is_not_ignored)
    all_passed = all_passed and engine_is_not_ignored

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
