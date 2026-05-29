import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.codex_runner import _extract_cli_token_usage


def fail(message):
    print("FAIL:", message)
    return False


def verify_tokens_used_block():
    usage = _extract_cli_token_usage(
        """
        other output

        tokens used
        20,578
        """
    )
    return usage.get("total_tokens") == 20578 or fail(
        "tokens used block should populate total_tokens"
    )


def verify_structured_total_wins():
    usage = _extract_cli_token_usage(
        """
        {"usage": {"total_tokens": 42}}
        tokens used
        20,578
        """
    )
    return usage.get("total_tokens") == 42 or fail(
        "structured total_tokens should not be overwritten"
    )


def verify_existing_parsers():
    usage = _extract_cli_token_usage(
        """
        {"token_usage": {"prompt_tokens": 11, "completion_tokens": 22}}
        total_tokens: 33
        """
    )
    checks = [
        ("input_tokens", 11),
        ("output_tokens", 22),
        ("total_tokens", 33),
    ]
    for key, expected in checks:
        if usage.get(key) != expected:
            return fail("%s should be %s" % (key, expected))
    return True


def main():
    checks = [
        verify_tokens_used_block(),
        verify_structured_total_wins(),
        verify_existing_parsers(),
    ]
    if all(checks):
        print("codex_token_usage_ok")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
