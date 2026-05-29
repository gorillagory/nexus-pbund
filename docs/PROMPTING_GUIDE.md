# Nexus Prompting Guide

## General Style

Use direct operator prompts. State the mission, current state, goal, safety rules, workflow, verification, git actions, and report path. Prefer one complete Codex operator prompt over many small copy/paste fragments.

## Codex Operator Prompt Style

Codex should inspect local context, make routine implementation decisions, run verification, commit, merge, tag, push when authorized, and write the report. The human should only approve risky direction or intervene on blockers.

## Packet Prompt Structure

- Mission.
- Current state / context.
- Goal.
- Safety Rules.
- Workflow.
- Files allowed.
- Parts A/B/C for implementation phases.
- Verification.
- Commit / Merge / Push.
- Report.

## Categories

- feature
- bugfix
- upgrade
- refactor
- infra
- testing
- docs
- security
- recovery
- analysis
- schema
- uiux
- discord
- git
- ci

## Reducing User Copy/Paste

- Use one Codex operator prompt.
- Let Codex run git, verification, and report writing itself.
- Write final reports to `/tmp`.
- Keep reusable successful prompts in the Prompt Vault.

## Safety Rails

- Do not expose API keys.
- Do not use `shell=True` or `subprocess.Popen`.
- Do not call execution routes unless explicitly allowed.
- Do not start Auto-Pilot unless explicitly building or testing it.
- Do not force push, reset, clean, or delete data without explicit instruction.
