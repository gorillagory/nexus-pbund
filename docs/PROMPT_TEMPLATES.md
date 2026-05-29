# Prompt Templates

These starter templates are also seeded into the Prompt Vault.

## Generic Feature Packet

Use for scoped product or platform additions. Include mission, current state, goal, safety rules, allowed files, implementation parts, verification, commit / merge / push, and `/tmp` report.

## Bugfix Packet

Use for diagnosing and fixing regressions. Lead with observed failure, expected behavior, suspected files, verification commands, and regression coverage.

## UI Polish Packet

Use for dashboard improvements. Require responsive layout, escaped text, no native alerts, no new execution behavior, `node --check`, and relevant verifier updates.

## Verification / Regression Packet

Use for no-token regression harnesses. Require mocks for CodexRunner or DB/session paths, no live endpoints, clear PASS lines, and nonzero exit on failure.

## Schema Sync Packet

Use when models or tables change. Require create/alter-only schema sync, no drop/truncate/delete, model import checks, and inspector or text verification.

## Operator Finalize Packet

Use when a packet is already committed and passing. Confirm clean git, fast-forward merge to main, run verification, tag, push, and report.

## Live Smoke Test Packet

Use only when explicitly approved. Limit live execution to the requested smoke path, restore execution mode, verify markers, and report safety outcomes.
