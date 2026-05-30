# Nexus Workflow Lock v1.0

Nexus is currently operating as a supervised factory. The locked workflow keeps decisions visible, keeps execution explicit, and lets Codex handle routine operator work after the human sets direction.

## Idea Capture

Capture raw ideas in the Orchestration Inbox before they become work. Do not execute from capture. Every idea must become a scoped task, work packet, document update, or explicit discard.

Packet 022 added the Orchestration Inbox foundation for manual capture and later triage. The inbox is supervised only: it stores raw intent, priority, category, status, and triage notes without calling Codex, task execution, packet execution, or Auto-Pilot routes.

Packet 023 added the Discord Event Router foundation. Discord-originated operator intent is captured into the Orchestration Inbox with source `discord`; Discord messages do not execute tasks, packets, Codex, or Auto-Pilot directly.

## Triage

Triage asks four questions:

- What outcome is required?
- What files or systems are allowed to change?
- What safety rules apply?
- What verification proves the work?

If the answers are unclear, Codex should inspect local context first and ask the human only when the decision is risky or cannot be inferred.

Discord-captured items follow the same triage rule as manual inbox items. Each captured message must become a scoped task, work packet, document update, or explicit discard before any supervised execution path is considered.

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

Packet 024 added Git Explorer as a read-only dashboard surface for branch, clean/dirty status, recent commits, baseline tags, changed files, diff stat, and bounded redacted diff previews. Git Explorer must not perform git writes. Branch Per Packet remains Packet 025.

Packet 025 added Branch Per Packet as a supervised branch preparation helper. Its only app-level git write is `git switch -c` for a validated `factory/packet-###-safe-slug` branch from clean `main` after explicit operator confirmation. It does not commit, merge, push, reset, clean, rebase, stash, tag, delete branches, or run arbitrary checkout.

Packet 026 added the Operator Intervention Queue as the human review and decision lane. It records blockers, required review, recommended actions, and operator notes. It does not execute tasks, run packets, run Codex, retry or continue failed runs, recover automatically, perform Git actions, or start Auto-Pilot. Recovery controls remain separate.

Packet 027 added Trusted Packet Mode as a supervised trust gate. Operators may mark reviewed work packets as trusted or revoke trust with explicit confirmation and a recorded reason. Enabling Trusted Packet Mode does not execute anything, does not unlock Auto-Pilot, and does not bypass explicit operator execution. When enabled, supervised packet execution rejects packets unless `trust_status=trusted`.

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

The dashboard Git Explorer is read-only. Operator/Codex may still perform routine git operations outside the app according to the packet workflow, but the app must not expose commit, merge, branch, tag, push, pull, fetch, reset, clean, rebase, stash, or checkout actions.

Branch Per Packet is the narrow exception for app-level git writes. It may prepare one validated packet branch at a time after clean-worktree checks. Codex operator workflow may still perform verified commit, fast-forward merge, baseline tag, and push outside the app.

The Operator Intervention Queue is record keeping only. It may create, acknowledge, resolve, dismiss, and update intervention records. It must not become a hidden execution, recovery, or Git write path.

Trusted Packet Mode is restrictive only. It may update packet trust metadata and settings, and it may block supervised packet execution for untrusted packets. It must not add autonomous execution, direct Codex execution, retry/continue automation, or Git write controls.

## Safety Rules

- no force push.
- No `git reset` or `git clean` unless explicitly requested.
- No destructive DB operations.
- No raw secrets in UI, logs, prompts, reports, or events.
- No Auto-Pilot unless explicitly building or testing it.
- No execution routes unless the packet explicitly permits them.

## Operator Rule

Codex should do routine operator tasks: repo checks, implementation, verification, commit, merge, tag, push, and `/tmp` reports. The human should approve major or risky direction and intervene on blockers.
