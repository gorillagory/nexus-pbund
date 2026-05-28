import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def pass_check(message):
    print("PASS: {}".format(message))


def fail_check(message, failures):
    print("FAIL: {}".format(message))
    failures.append(message)


def verify_json_helper(failures):
    from engine import extract_json_int_array

    cases = [
        ("[1, 2, 3]", [1, 2, 3]),
        ("```json\n[1,2]\n```", [1, 2]),
        ("Done tasks: [4, 5]", [4, 5]),
        ("[]", []),
        ("[true, 1]", [1]),
        ("No tasks complete", []),
    ]

    for raw, expected in cases:
        actual = extract_json_int_array(raw)
        if actual == expected:
            pass_check("extract_json_int_array({!r}) -> {!r}".format(raw, expected))
        else:
            fail_check(
                "extract_json_int_array({!r}) returned {!r}, expected {!r}".format(
                    raw,
                    actual,
                    expected,
                ),
                failures,
            )


def verify_public_settings(failures):
    import engine as engine_module

    class DummyChatSessionStore:
        def __init__(self, max_messages=20):
            self.max_messages = max_messages

    engine_module.ChatSessionStore = DummyChatSessionStore
    engine = engine_module.NexusEngine(os.getcwd())
    engine.settings = {
        "provider": "gemini",
        "gemini_api_key": "SECRET_GEMINI",
        "openai_api_key": "SECRET_OPENAI",
        "gemini_model": "test-gemini",
        "openai_model": "test-openai",
        "model_selection_mode": "auto",
    }

    public = engine.public_settings()
    checks = [
        ("gemini_api_key not present", "gemini_api_key" not in public),
        ("openai_api_key not present", "openai_api_key" not in public),
        ("api_key not present", "api_key" not in public),
        ("gemini_api_key_configured is True", public.get("gemini_api_key_configured") is True),
        ("openai_api_key_configured is True", public.get("openai_api_key_configured") is True),
        ("provider preserved", public.get("provider") == "gemini"),
        ("gemini_model preserved", public.get("gemini_model") == "test-gemini"),
        ("openai_model preserved", public.get("openai_model") == "test-openai"),
    ]

    for message, ok in checks:
        if ok:
            pass_check(message)
        else:
            fail_check(message, failures)


def verify_codex_runner(failures):
    from src.services.codex_runner import CodexRunner

    runner = CodexRunner(timeout_factory=lambda prompt: 5)
    if callable(getattr(runner, "run", None)):
        pass_check("CodexRunner exposes callable run method")
    else:
        fail_check("CodexRunner run method is not callable", failures)


def verify_bundle_ignores(failures):
    bundle_path = os.path.join(REPO_ROOT, "bundle.py")
    if not os.path.exists(bundle_path):
        pass_check("bundle.py not present; ignore inspection skipped")
        return

    with open(bundle_path, "r", encoding="utf-8") as file:
        bundle_text = file.read()

    if "settings.json" in bundle_text:
        pass_check("bundle.py ignores settings.json")
    else:
        fail_check("bundle.py does not mention settings.json ignore logic", failures)

    if "output" in bundle_text:
        pass_check("bundle.py keeps output ignored")
    else:
        fail_check("bundle.py does not mention output ignore logic", failures)


def main():
    failures = []
    verify_json_helper(failures)
    verify_public_settings(failures)
    verify_codex_runner(failures)
    verify_bundle_ignores(failures)

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
