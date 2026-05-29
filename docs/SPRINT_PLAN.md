# Nexus Sprint Plan

## Current State

Nexus is in Supervised Factory Alpha.

Completed capabilities:

- Supervised packet runner.
- Run One Task.
- Factory Console visibility.
- Recovery controls and audit notes.
- Local and CI preflight.
- No-token regression harness.
- CI status ingestion without GitHub API credentials.
- Operator UX polish.
- Packet 022 Orchestration Inbox foundation for supervised idea capture and triage.

## Sprint 2 Goal

Remote-operable supervised factory. The operator should be able to capture intent, select a trusted prompt, stage work, supervise one task or one packet, recover from failures, and understand state from the dashboard.

## Recommended Packet Roadmap

1. Prompt Vault. Complete.
2. Orchestration Inbox. Complete as Packet 022 foundation.
3. Discord Event Router.
4. Git Explorer.
5. Branch Per Packet.
6. Operator Intervention Queue.
7. Trusted Packet Mode.

Inbox capture rule: raw ideas are captured first, then triaged into a scoped task, work packet, document update, or explicit discard. The inbox must not execute work.

Do not build full Auto-Pilot yet. Keep the system supervised, inspectable, and reversible.
