---
kind: trigger
schedule: "*/5 * * * *"
target_kind: agent
target: hello-world
prompt: Tell me one cheerful fact about right now.
---
Phase 9 smoke trigger — fires every 5 minutes against `hello-world` to
demonstrate the scheduler end-to-end. Lands in the runs table with
`triggered_by: heartbeat` so the UI can label it as scheduler-driven.
