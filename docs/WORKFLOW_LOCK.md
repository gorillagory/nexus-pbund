# Nexus Workflow Lock v1.0

Nexus is currently operating as a supervised factory. The locked workflow keeps decisions visible, keeps execution explicit, and lets Codex handle routine operator work after the human sets direction.

## Idea Capture

Capture raw ideas in the dashboard, chat, prompt vault, or a future inbox. Do not execute from capture. Every idea must become a scoped task, work packet, document update, or explicit discard.

## Triage

Triage asks four questions:

- What outcome is required?
- What files or systems are allowed to change?
- What safety rules apply?
- What verification proves the work?

If the answers are unclear, Codex should inspect local context first and ask the human only when the decision is risky or cannot be inferred.

## Packet Drafting

Packets use the Codex operator prompt structure:

- Mission
- Current state / context
- Goal
- Safety rules
- Workflow
- Files allowed
- Parts A/B/C as needed
- Verification
- Commit / merge / push instructions
- Report path under `/tmp`

## Prompt Vault Usage

Reusable prompts belong in the Prompt Vault. Use categories such as feature, bugfix, upgrade, refactor, infra, testing, docs, security, recovery, analysis, schema, uiux, discord, git, and ci.

The vault is for storing and copying prompts. It must not execute Codex, start Auto-Pilot, or call packet execution routes.

## Staging To Kanban

Drafted work can be staged to Kanban when it is scoped and has safety rules. Staging is not execution. Staged work is reviewed in the board before a supervised mode runs it.

## Supervised Execution Modes

- `manual`: no automation. The operator inspects, edits, stages, and copies commands.
- `one_task`: run exactly one selected task.
- `one_packet`: run exactly one selected work packet.
- `autopilot`: locked for future work. Do not use unless explicitly building or testing Auto-Pilot.

Automatic analysis is enabled only for Auto-Pilot.

## Factory Console Visibility

The Factory Console is the operator surface for mode, automatic analysis state, Git state, preflight, CI metadata, recent events, execution runs, changed files, and recovery actions.

## Recovery Flow

When a run fails:

1. Inspect the failed run details.
2. Read stdout, stderr, changed files, and related events.
3. Add an operator note.
4. Mark review required, retry one task in `one_task`, or continue one packet in `one_packet`.
5. Verify and record outcomes as factory events.

## Preflight And CI

Run local preflight before merge:

```bash
python3 scripts/nexus_preflight.py --quick
```

GitHub Actions runs quick strict preflight on push and pull request to `main`.

## Git And Tag Baseline Practice

Use a packet branch, verify locally, commit, fast-forward merge to `main`, verify again, tag a baseline, and push `main` plus the tag.

## Safety Rules

- no force push.
- No `git reset` or `git clean` unless explicitly requested.
- No destructive DB operations.
- No raw secrets in UI, logs, prompts, reports, or events.
- No Auto-Pilot unless explicitly building or testing it.
- No execution routes unless the packet explicitly permits them.

## Operator Rule

Codex should do routine operator tasks: repo checks, implementation, verification, commit, merge, tag, push, and `/tmp` reports. The human should approve major or risky direction and intervene on blockers.
