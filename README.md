# Scientific Assistants

Ji Eun and Ji An: persistent personal and scientific assistants built around Hermes and the Codex app-server harness, using the owner's existing Codex subscription.

Ji Eun handles conversation, context, planning and everyday work through Discord and WhatsApp Message yourself. She defaults to Luna and routes everyday work to Terra. Ji An uses GPT-6.1 Sol for scientific interpretation, methodology and experiment review. They share structured topic/time-scoped memory, a durable task board and bounded teammate handoffs.

## Included

- Peer-checked Unix-socket MCP broker for structured memory, reminders and progress.
- Owner-only Discord and WhatsApp integration, deterministic durable delivery and offline recovery.
- Gmail/Google Calendar MCP integration and read-only Notion/Slack context setup.
- Isolated GCP/SSH research broker for explicitly requested tasks, with durable IDs, logs and cancellation.
- Private server dashboard, Discord activity/health panels and systemd service templates.
- Deployment/follow-up scripts, policies and regression tests.

Voice is disabled. Separate iCloud calendars are not connected. Selected WhatsApp chat/group ingestion is pending explicit scope. Claude Code is deferred by the owner. No paid inference fallback is configured.

## Autonomous code maintenance

Ji Eun and Ji An now maintain a writable checkout under `/var/lib/personal-agent/workspaces/scientific-assistants`. They can edit and extend application code, run isolated checks, obtain source-bound Sol peer reviews, deploy allowed files and roll back releases through a separate maintenance MCP service. No general sudo or access to `/root` is needed.

The private dashboard shows candidate changes, check logs, reviews and actual release state. Owner stop takes priority over updates; failed recovery preserves its journal and blocks later queued releases. Read [SELF-MAINTENANCE.md](SELF-MAINTENANCE.md) for the workflow and deployment scope.

## Latency design — proposed, not implemented

Read [the network and latency design](design/latency-network-design.md) for measurements and the proposed event-driven architecture: streamed answers, bounded context, socket wakeups, deadline-driven reminders and research event streams. This is a review document; publishing it does not authorize or deploy those changes.

## Repository layout

| Path | Purpose |
| --- | --- |
| `app/` | Local brokers, state, scheduling, research execution and monitor backend |
| `plugin/` | Hermes personal-context integration |
| `mission-control/` | Private dashboard frontend |
| `systemd/` | Service and timer templates |
| `tests/` | Python and JavaScript regression tests |
| `maintenance/` | Scoped deploy broker, unprivileged MCP source tools and fixed isolated checks |
| `whatsapp-bridge/` | Pinned bridge source and regression tests, with its upstream license |
| `design/` | Proposed network/latency design |
| `docs/deployed-server.md` | Detailed existing server operations and setup history |
| `upstreams.json` | Pinned upstream references; no vendored runtimes |

## Development checks

Use Python 3.11+ and Node.js 22+. These checks do not require Discord tokens, cloud logins, model inference or a running Hermes installation:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -q
node --test tests/whatsapp-pairing-compat.test.mjs
node --check mission-control/app.js
```

The self-maintenance candidate passed 68 Python tests and 32 Node test results, including the upstream bridge regressions. Full bridge tests require its npm dependencies; the deployed isolated runner mounts the already installed dependencies read-only. The base JavaScript tests above use only built-in modules. Live platform validation is separate from these unit/integration tests.

## Deployment boundary

This is a source snapshot of an existing private server deployment, not a portable one-command installer. Scripts contain the owner's deployment-specific service paths, non-secret account identifiers and host allowlists. Review those values, dependencies and script ordering before using them on another machine. Installers must not be run automatically from CI or merely to validate this repository. `deploy.py` is initial bootstrap only and refuses an existing installation; follow-up installers have narrower scopes.

The live installation is `/opt/personal-agents`; the bots maintain source in `/var/lib/personal-agent/workspaces/scientific-assistants`. `/root/personal-agents` retains the administrator bootstrap source. This release adds the explicitly owner-authorized self-maintenance path; it does not implement the latency proposal. [Operational documentation](docs/deployed-server.md) describes the installed system and remaining connection limits.

## Credentials and private data

No bot tokens, linked-device credentials, OAuth/cloud logins, SSH keys, account credential files, runtime databases, conversation transcripts, private memory or backups are included. They remain in protected service homes or systemd credentials. `.gitignore` excludes those classes of files. Review staged content before every push; do not export `/var/lib/personal-agent*`, `/etc/personal-agents`, or `/root/shared-memory` into this repository.

Hermes, Node and bridge dependencies are installed separately. The reviewed WhatsApp pairing compatibility backport has its own source/manifest and [third-party notice](THIRD_PARTY_NOTICES.md). No license is granted here for unrelated project code merely by recording an upstream notice.
