# Planet Improvement Lab

The lab runs every six hours in a systemd service alongside the Ji Eun and Ji An gateways. Ji Eun, Ji An and an engineering teammate independently propose an improvement, receive one another’s proposals, and publish their critiques. Ji Eun decides whether there is a testable change. The cycle can also compare available subscription models on a small synthetic routing fixture and records accuracy and elapsed time.

Each cycle uses Git-tracked public Planet source and public research. The next cycle considers previous results and proposed follow-up files. The lab creates an isolated checkout, records the debate on a GitHub branch, and puts a candidate and regression in a later commit. It runs the new regression on the original and the patched code through the existing maintenance broker. Where the regression demonstrates an improvement, Ji An and a separate Sol review session assess its exact diff. An experiment remains visible when it fails or a reviewer asks for changes.

An approved application change can deploy after its GitHub push, provided it matches the live release outside the debated change. The maintenance broker waits until the gateways are idle and uses its existing health checks and rollback. Changes that need integration remain on the run branch with the evidence. Model experiments use the existing subscription and leave the live routing defaults in place.

- [Private Improvement Lab](https://ji-eun-ji-an-lab.smudge0110.chatgpt.site)
- [Planet improvement branches](https://github.com/Deceptrax123/Planet/branches/all?query=improvement)
- [Self-maintenance workflow](../SELF-MAINTENANCE.md)

## Operation

`systemctl list-timers personal-agent-improvement.timer` shows the schedule. `journalctl -u personal-agent-improvement.service` shows lifecycle records. `systemctl start personal-agent-improvement.service` starts a cycle on demand. `systemctl disable --now personal-agent-improvement.timer` pauses automatic launches.

The service runs as `personal-agent`. It uses the existing subscription, a Planet-only Git SSH deploy key and an encrypted Sites service credential. The writable state lives in `/var/lib/personal-agent/planet-lab`. Install `lab.py` and `../maintenance/protocol.py` in `/opt/personal-agents/improvement` and use the two supplied systemd units. The SSH key and strict GitHub host entries live under the service user's `.ssh` directory. The Git record contains public project contributions and test summaries. Personal chat, memory, raw service logs and credentials are outside the lab inputs.

The monitor reads a revisioned snapshot from an owner-private Sites Worker. The worker source in `improvement-monitor` is packaged with its own Site identity generated at deployment, its D1 migration, and the output of `node build.mjs`. The host validates each update by reading the revision back.
