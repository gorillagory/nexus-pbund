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

## Sprint 2 Goal

Remote-operable supervised factory. The operator should be able to capture intent, select a trusted prompt, stage work, supervise one task or one packet, recover from failures, and understand state from the dashboard.

## Recommended Packet Roadmap

1. Prompt Vault.
2. Orchestration Inbox.
3. Discord Event Router.
4. Git Explorer.
5. Branch Per Packet.
6. Operator Intervention Queue.
7. Trusted Packet Mode.

Do not build full Auto-Pilot yet. Keep the system supervised, inspectable, and reversible.
