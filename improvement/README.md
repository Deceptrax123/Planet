# Planet Improvement Lab

The lab runs every six hours in a systemd service alongside the Ji Eun and Ji An gateways. Both leads pick their debate models and recruit task-specific teammates from the connected catalog. Each participant proposes an improvement and critiques the other proposals. Ji Eun records which ideas advanced, were combined, were deferred, or were rejected, with her reasons. The cycle can also compare available subscription models on a small synthetic routing fixture and records accuracy and elapsed time.

Each cycle uses Git-tracked public Planet source and public research. The next cycle considers previous results and proposed follow-up files. The lab creates an isolated checkout, records the debate on a GitHub branch, and puts a candidate and regression in a later commit. It runs a repair regression on the original and patched code through the existing maintenance broker. A harness-only experiment tests unchanged code and an intentional mutation. GitHub receives the harness without the intentional defect. Where the regression demonstrates an improvement, Ji An and a separate Sol review session assess its exact diff. An experiment remains visible when it fails or a reviewer asks for changes.

An approved application change can deploy after its GitHub push, provided it matches the live release outside the debated change. The maintenance broker waits until the gateways are idle and uses its existing health checks and rollback. When unrelated live application files differ from GitHub, the broker tests against those deployed versions without publishing them. Changes that need integration remain on the run branch with the evidence. Model experiments use the existing subscription and leave the live routing defaults in place.

- [Private Improvement Lab](https://ji-eun-ji-an-lab.smudge0110.chatgpt.site)
- [Planet improvement branches](https://github.com/Deceptrax123/Planet/branches/all?query=improvement)
- [Self-maintenance workflow](../SELF-MAINTENANCE.md)

## Operation

`systemctl list-timers personal-agent-improvement.timer` shows the schedule. `journalctl -u personal-agent-improvement.service` shows lifecycle records. `systemctl start personal-agent-improvement.service` starts a cycle on demand. `systemctl disable --now personal-agent-improvement.timer` pauses automatic launches.

The service runs as `personal-agent`. It uses the existing subscription, a Planet-only Git SSH deploy key and an encrypted Sites service credential. The writable state lives in `/var/lib/personal-agent/planet-lab`. Install `lab.py` and `../maintenance/protocol.py` in `/opt/personal-agents/improvement` and use the two supplied systemd units. The SSH key and strict GitHub host entries live under the service user's `.ssh` directory. The assistant checkout has a `planet` remote for direct pushes such as `git push planet HEAD:refs/heads/<branch>`. The Git record contains public project contributions and test summaries. Personal chat, memory, raw service logs and credentials are outside the lab inputs.

The monitor reads a revisioned snapshot from an owner-private Sites Worker. The worker source in `improvement-monitor` is packaged with its own Site identity generated at deployment, its D1 migration, and the output of `node build.mjs`. The host validates each update by reading the revision back.

### Daily recap

The chart groups timestamped lab activity by India time. It shows each agent's contributions, shared runs, arguments, discarded ideas, tests, and release outcomes. The current day updates with the live feed. At 00:05 India time, `personal-agent-daily-recap.timer` runs `daily_report.py` to archive the prior day. The report runs with the site closed and uses existing records.

Install `daily_report.py` alongside `lab.py` and enable the two `personal-agent-daily-recap` units. The daily writer reuses the monitor's existing service credential and reads back each saved report.

For ordinary tasks, both leads can compose a team with native delegation and use Kanban's `assignee`, `model`, and `provider` fields to route durable work to a connected provider. The current lab catalog comes from the authenticated Codex installation.
