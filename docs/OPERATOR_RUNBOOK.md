# Nexus Operator Runbook

Nexus is a Supervised Factory Alpha system. Operators capture intent, review and stage work, run explicit supervised execution only when chosen, recover deliberately, verify locally, tag a baseline, and hand off repo truth to the next chat.

## Starting The App Locally

```bash
cd ~/garage/workspaces/nexus-pbund
python3 -c 'import os; from engine import NexusEngine; from dashboard import NexusDashboard; NexusDashboard(NexusEngine(os.getcwd())).run(5055)'
```

Open `http://localhost:5055`.

Before work:

```bash
git status --short
git log --oneline --decorate -20
python3 scripts/nexus_preflight.py --quick
```

For a packet:

```bash
python3 scripts/nexus_preflight.py --packet 36 --report /tmp/nexus-preflight-packet-036.md
```

## Server-Side Codex Job Runner

Use the Server-Side Codex Job Runner, or `tmux`, for long Codex work from a phone or unstable SSH client. Do not run long Codex jobs in raw phone SSH foreground because the client can disconnect while the server-side work is still running without a durable report path.

Create a prompt file outside the repo or under `/tmp`, then start a detached job:

```bash
python3 scripts/nexus_codex_job.py start --name packet_039 --prompt-file /tmp/packet-039-prompt.txt --expect-report /tmp/nexus-packet-039-server-side-codex-job-runner-report.md
```

The start command prints the job id, job directory, combined log path, and status path. Job data is stored under `/tmp/nexus-codex-jobs/<job-id>/` with `prompt.txt`, `combined.log`, `runner.log`, `status.json`, `pid`, `started_at`, and `finished_at` when complete. The runner records report expectation only; it does not write reports into the repo by default.

Check status after a disconnect:

```bash
python3 scripts/nexus_codex_job.py list
python3 scripts/nexus_codex_job.py status --job-id <job-id>
python3 scripts/nexus_codex_job.py tail --job-id <job-id>
```

To stop a job, use only the recorded job id:

```bash
python3 scripts/nexus_codex_job.py stop --job-id <job-id>
```

The stop command targets only the PID recorded for that job and verifies the process where possible. Do not use broad `pkill`, `killall`, force push, reset, or clean as recovery shortcuts. If SSH drops, reconnect, run `list`, inspect `status`, tail the log, check the expected report path, then resume normal verification and Git workflow.

## Factory Console

- Use Simple Operator Flow as the primary lane for normal work: type the request, generate and review the draft, prepare one work packet, evaluate readiness, explicitly approve one run, and track the result.
- Use Command Center for mode, preflight, CI, Git Explorer summary, and Branch Per Packet status.
- Use Intake & Triage for Orchestration Inbox, inbox conversion, and Discord capture status.
- Use Packet Preparation for Work Packet Manager, Packet Drafting Assistant, Readiness Checklist, and Trusted Packet Mode.
- Use Human Review for Operator Intervention Queue, Operator Review History, and recovery visibility.
- Use Vault & Settings for Prompt Vault, provider settings, resources, and history.

## Simple Operator Flow

Simple Operator Flow is the default mobile-friendly path for normal supervised work:

1. Type the operator request in the Simple Operator Flow panel.
2. Confirm capture with `confirm_create=true`.
3. Generate a structured Codex prompt draft with `confirm_generate=true`.
4. Review or edit the draft before preparation.
5. Prepare one untrusted work packet with `confirm_prepare=true`.
6. Evaluate readiness with `confirm_evaluate=true`.
7. If Trusted Packet Mode is enabled, explicitly trust the packet through the existing trust controls.
8. Switch to `one_packet` mode and approve exactly one selected run with `confirm_run=true`.
9. Track status, timestamps, stdout/stderr snippets, changed files, verification result, and report expectation from the tracking panel.

Advanced modules remain available for deeper review, recovery, Prompt Vault management, Git Explorer, Branch Per Packet, and intervention history, but they are secondary to the Simple Operator lane for routine work.

Execution requires explicit approval. Discord remains capture/notification-only.

Simple Operator Flow does not start Auto-Pilot, does not call `/api/tasks/auto-run`, does not execute from Discord, does not retry or continue automatically, does not mark packets trusted automatically, does not bypass Trusted Packet Mode, and does not add Git commit, merge, push, reset, clean, rebase, stash, tag, delete, or broad write controls to the app.

## Mobile Operator Alerts

Use Mobile Operator Alerts when away from the terminal and needing phone awareness. Alerts are outbound Discord notifications only. They do not create a Discord command surface and cannot execute Codex, tasks, packets, Git actions, trust changes, retry/continue behavior, or Auto-Pilot.

Configure locally with environment variables or saved settings:

```bash
NEXUS_OPERATOR_NOTIFY_DISCORD_ENABLED=true
NEXUS_OPERATOR_NOTIFY_DISCORD_WEBHOOK_URL=<discord webhook url>
NEXUS_OPERATOR_DASHBOARD_URL=<operator dashboard url>
NEXUS_OPERATOR_NOTIFY_MIN_SEVERITY=info
NEXUS_OPERATOR_NOTIFY_COOLDOWN_SECONDS=30
```

Use a Tailscale, VPN, or approved tunnel URL for `NEXUS_OPERATOR_DASHBOARD_URL` if the dashboard needs mobile access. Do not expose the dashboard publicly without an operator-approved access control layer.

From Factory Console:

1. Confirm Mobile Operator Alerts show enabled or disabled.
2. Confirm webhook and dashboard URL show configured/not configured only.
3. Use Test Notification to send a notification-only alert.
4. Keep acting from the terminal or dashboard. Do not attempt mobile execution through Discord.

Notification messages must not include raw webhook URLs, API keys, full stdout/stderr, raw environment values, or secrets.

## Capture And Triage

Capture raw ideas in Orchestration Inbox first. Discord-captured intent also lands in the inbox and remains capture-only. Every inbox item must become a scoped task, staged untrusted work packet, document update audit candidate, or audited discard.

Conversion is not execution. Converted work packets remain untrusted until explicitly reviewed and trusted.

## Packet Preparation

1. Draft the packet prompt with Packet Drafting Assistant or Prompt Vault templates.
2. Check readiness for mission, safety rules, files allowed, verification, report path, and trust visibility.
3. Use Work Packet Readiness Checklist before trust or supervised execution.
4. Use Branch Per Packet only to prepare one validated `factory/packet-###-safe-slug` branch from clean `main`.
5. Mark a packet trusted only after review, explicit confirmation, and a reason.
6. Run one task or one packet only through explicit supervised execution modes.

## Review And Recovery

- Use Operator Intervention Queue for blockers, required decisions, and recommended actions.
- Use Operator Review History for audit visibility and manual review notes.
- Use recovery controls to inspect failed runs, stdout, stderr, changed files, and events.
- Retry or continue requires explicit approval and the appropriate supervised mode.

## Git And Baselines

Normal packet workflow:

```bash
git switch -c factory/packet-###-safe-slug
python3 scripts/nexus_preflight.py --packet ### --report /tmp/nexus-preflight-packet-###.md
git add <scoped files>
git commit -m "<packet summary>"
git switch main
git merge --ff-only factory/packet-###-safe-slug
git tag nexus-<packet-baseline>-2026-05-30
git push origin main
git push origin nexus-<packet-baseline>-2026-05-30
```

Do not force push. Do not use `git reset` or `git clean` unless explicitly approved.

## New Chat Handoff

Use repo truth:

```bash
cd ~/garage/workspaces/nexus-pbund
git status --short
git log --oneline --decorate -20
python3 scripts/nexus_preflight.py --quick
python3 scripts/nexus_preflight.py --list-packet-checks
cat docs/CHAT_HANDOFF.md
cat docs/WORKFLOW_LOCK.md
cat docs/SPRINT_PLAN.md
cat docs/SPRINT_3_PLAN.md
cat docs/SPRINT_4_PLAN.md
cat docs/OPERATOR_RUNBOOK.md
cat docs/DEPLOYMENT_RUNBOOK.md
cat docs/RECOVERY_RUNBOOK.md
```

## Do Not Do

- No Auto-Pilot unless explicitly building or testing it.
- No direct Discord execution.
- No destructive database operations.
- No raw secret exposure in docs, reports, UI, API responses, events, inbox items, or prompts.
- No raw Discord webhook URL exposure in docs, reports, UI, API responses, events, notifications, or prompts.
- Git Explorer is read-only.
- No force push, reset, clean, branch deletion, or broad Git write controls in the app.
- No `shell=True`. No `subprocess.Popen` in dashboard.py or src/services. The narrow exception is `scripts/nexus_codex_job.py`, which uses `subprocess.Popen` only to launch a detached local operator job runner after a human explicitly runs the CLI.
- No native browser `alert()` or `confirm()`.
