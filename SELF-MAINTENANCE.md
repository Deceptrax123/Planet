# Application self-maintenance

Ji Eun and Ji An can edit their maintained checkout at `/var/lib/personal-agent/workspaces/scientific-assistants` and deploy application fixes and new capabilities using existing authorized integrations. Source access no longer depends on `/root` or sudo.

1. Read/edit source with the maintenance MCP tools (or normal workspace tools).
2. Add useful regression coverage and commit local history.
3. `self_code_prepare` creates an immutable source snapshot and runs Python/Node checks as `personal-agent-build`, with private networking, no credentials, resource limits and read-only source. Poll `self_code_status` for results and logs.
4. Ji An and a distinct GPT-6.1 Sol peer inspect `self_code_diff` and `self_code_candidate_read`. They record source-bound reviews using their actual native thread IDs. These attestations document the workflow; they are not cryptographic proof of independent model judgment.
5. `self_code_deploy` queues a checked, approved application release. The separate broker waits for idle conversations, journals previous code, stops the application services, replaces only allowed files, restarts them and checks Discord, WhatsApp and the data broker. A failed release restores its previous code. A server restart recovers an interrupted transaction. Pending recovery blocks later queued releases; `self_code_recover` retries only the original recorded restoration.
6. Inspect final status. `self_code_rollback` restores the previous code of the current managed release. Logs, tests, reviews and release state appear in the private mission-control dashboard and normal activity monitoring.

Automatically deployable paths are direct Python modules under `app/`, dashboard JS/CSS/HTML, and WhatsApp bridge JS/MJS. Root-run `control.py`, `backup.py`, `shared_sync.py`, standard-library shadow modules, systemd units, deployment helpers and the maintenance service itself are excluded. Tests never execute as root. The bots have no general sudo. New credentials, paid services, cloud resource changes or new system privileges retain their normal authorization requirements.

The fixed administrator-owned runner and broker live under `/opt/personal-agents/maintenance`; durable manifests, reviews and rollback state are root-controlled under `/var/lib/personal-agent-maintenance`. The writable source tree contains code only. Authentication and private memory stay in their existing homes.

Git commits remain local until published through an authorized GitHub integration. The initial local history is a deployment snapshot, not a clone of GitHub history. Existing owner stop/pause controls remain effective; deployments wait while paused. The earlier latency proposal has not been implemented.
