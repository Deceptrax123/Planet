# Ji Eun

Personal Hermes teammates on this server, using the owner's existing Codex subscription. No paid inference fallback and no voice.

## Talk and observe

DM **Ji Eun** or **Ji An**, or mention either in the Discord server. Only Discord owner `562571259758772254` and the verified WhatsApp owner self-chat are allowed to initiate work. Conversation replies are natural and direct; raw tool progress and interim workflow narration are disabled across all profiles.

- [Agent activity](https://discord.com/channels/1248530615662284810/1569058485033894160): agent starts, finishes, failures and delegated sessions; no tool payloads or private task content.
- [Operations status](https://discord.com/channels/1248530615662284810/1569058490692149299): a continuously updated service/reminder health panel. These two monitoring channels are restricted to the owner and bot; Discord administrators retain their normal access.
- Mission control: **http://127.0.0.1:9120** on the server. Parent/child agent tree, actual models and lifecycle, visible session messages, tool calls/results, task dependencies, handoff comments and failures. Internal reasoning is excluded. Recent 60 sessions / 160 visible events per session. Polls every three seconds. Historical sessions remain visible; idle agents do not make model calls.
- Terminal: `personal-agent-monitor --watch`.

To open the dashboard from a Mac, keep an SSH tunnel running:

```sh
ssh -N -L 9120:127.0.0.1:9120 YOUR_SSH_HOST
```

Then open http://127.0.0.1:9120. Username: `ji-eun`. In your interactive server terminal run `sudo personal-agent-control monitor-password` to display the password. Do not paste it into chat. The dashboard binds only to loopback and is password protected. Its service runs as `personal-agent`, not root. It is not exposed publicly.

The page can pause/resume new work. Existing turns finish when paused. Full stop and restart require the server terminal:

```sh
sudo personal-agent-control stop
sudo personal-agent-control start
```

Full stop halts gateway turns, scheduled inference, reminder sends, managed Kanban worker scopes and the research dispatcher. Remote research jobs remain running until individually cancelled; stopping the assistant does not destroy them. Both monitors remain available. Direct terminal owner controls require root; agents cannot call them. Subscription limits, account expiry or provider outages can still interrupt service.

## Team

| Role | Default model | Work |
|---|---|---|
| Ji Eun coordinator | Luna; Terra through the everyday role | Conversation, context, routing and consolidation |
| Inbox | Luna | Gmail searches and commitments |
| Planner | Luna | Calendars, scheduling and reminders |
| Everyday | Terra | Writing, food and practical assistance |
| Research | Sol | Scientific search and difficult reasoning |
| Ji An | GPT-6.1 Sol (`gpt-6.1-sol`) | Scientific interpretation, experiment analysis and methodological review |
| Subscriptions | Sol | Renewal evidence and usefulness reviews |

Every specialist can recruit teammates through native Codex subagents or durable Hermes Kanban tasks and handoff comments. Native concurrency is two children per session; durable worker concurrency is one, with one per profile. Instructions bound delegation to two levels and three handoffs; those depth/handoff limits are agent instructions, not a global hard enforcement mechanism. Kanban automatically stops tasks after their runtime cap and blocks repeated real failures. There is no promise of unlimited concurrent swarms.

## Memory and schedules

Structured SQLite memory tracks topic, source, confidence, confirmation, valid times, timezone, recurring windows, review dates and corrections. Relevant evidence is retrieved before each Hermes turn; native children explicitly retrieve their own context. Food requests retrieve health/nutrition/routine/preferences even without keyword overlap. A remembered preference is not a medical diagnosis. No health condition was seeded during setup.

Runtime state: `/var/lib/personal-agent-data/assistant.sqlite`, protected by a separate data account and Unix-socket MCP broker. Dynamic export: `/var/lib/personal-agent-data/exports/memory.json`. The root memory-sync timer copies credential-free exports to `/root/shared-memory/personal-agents/memory.json` and publishes curated shared records into a read-only runtime snapshot every minute. `/root/shared-memory` remains the portable shared source.

Forgetting removes live content and the current export, retaining a content-free tombstone. Protected older backups expire after 14 snapshots; shared-memory archives and native conversation logs need separate explicit cleanup if the user wants those erased too.

Daily brief: **09:00 Asia/Kolkata**, cron ID `1ebf9eab6cf5`. Standalone reminder quiet hours **23:00–09:00**, except explicit overnight requests. The owner explicitly permits proactive conversation at any time; there is no proactive quiet-hour rule or fixed message frequency. The brief checks today's agenda, urgent recent mail and priorities, with source availability stated. Sundays include a subscription review. It has no iPhone/Mac usage telemetry; receipts cannot establish whether an app is unused.

Nightly local memory review: **02:00 Asia/Kolkata**, cron ID `ad4ee5ddabce`. No mailbox scan in this job. Standalone reminders use a durable code-only scheduler and Discord outbox. Ambiguous network sends are flagged instead of blindly repeated. Event reminders should use provider-native alerts because standalone reminders do not automatically follow calendar edits.

Gmail and Google Calendar use the service account's authenticated **Codex MCP apps**, with matching account identities verified by actual profile calls. Notion and Slack are also enabled as read-only context sources: Nitish’s Space and Nitish/srinitishsri in Lossfunk. Actual identity checks, a Notion page read, and a narrow Slack search passed through Ji Eun. All other Notion/Slack tools are disabled by default; 41 Notion and 18 Slack tools annotated read-only were enabled, with qualified aliases for the native harness. This supersedes the earlier wrong-account Slack pause only for the verified workspace/account. No separate Google OAuth application is needed. iCloud is a separate connection and must be available to this service account before it can read those calendars. Unavailable sources must be stated in the brief. WhatsApp Message yourself is connected and owner-only delivery was verified.

## Operations

Source: `/root/personal-agents`. Installed app: `/opt/personal-agents/app`. Hermes v0.23.0 is pinned at commit `2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19` in `/opt/personal-agents/hermes-agent`; no vendor core changes.

Services: `personal-agent-gateway`, `personal-agent-ji-an`, `personal-agent-research`, `personal-agent-data`, `personal-agent-reminders`, `personal-agent-monitor` (Hermes admin UI on loopback 9119), `personal-agent-mission-control` (9120), and `personal-agent-discord-monitor`. All are enabled at boot. The dedicated agent's user manager has lingering enabled so durable workers can survive gateway restarts. The gateway keeps `/root` and `/home` inaccessible and exposes only its own user-manager IPC sockets for those workers.

```sh
sudo systemctl status personal-agent-gateway personal-agent-data personal-agent-reminders
sudo journalctl -u personal-agent-gateway -f
sudo journalctl -u personal-agent-discord-monitor -f
```

The root-only bot credential is in `/etc/personal-agents/discord.token`; services receive it through systemd credentials. Codex/Hermes authentication remains in the dedicated service home `/var/lib/personal-agent`, separate from the desktop account. Authentication files are never copied into shared memory or data backups. Reauthentication, if ever required, must use supported interactive login under the service identity.

Encrypted backups run nightly at approximately 02:30 India time (`21:00 UTC` plus jitter). `/var/backups/personal-agents` retains 14 encrypted snapshots; `/etc/personal-agents/backup.key` is needed for recovery. Each backup has an HMAC sidecar, is decrypted into a temporary directory and its SQLite snapshots are checked there with `PRAGMA integrity_check`. First isolated restore check passed. Keep a separately protected copy of the key; it is intentionally excluded from the backup. Recover into a separate directory first, verify the HMAC before decrypting, stop writers, then restore each database to its recorded location with the correct owner. Never unpack over live data.

`deploy.py` is initial bootstrap only and refuses to overwrite an existing deployment. `install-monitor.py`, `setup-discord-monitor.py`, and `set-chat-style.py` are narrow follow-up installers. Unit templates in `systemd/` reflect the deployed server. Preserve the managed Hermes callback block in `codex/config.toml`; rerunning bootstrap or replacing that file would break native tools. Install code changes without touching authentication files, then restart only affected services after active work finishes.

Verification: 31 unit/integration tests cover temporal recall, correction/forgetting, reminder retries/deduplication, MCP protocol, visible-log filtering, authentication, host/origin controls and rejected privileged web actions. Live checks passed for Luna conversation, Terra child delegation, Sol durable workers, memory retrieval, Gmail/Calendar profile identity, Discord delivery, service restart, scheduled memory-review execution and backup restoration. The web endpoints are checked live; a browser-rendering check has not yet been performed on this host.

Skills used: [OpenAI Docs](/root/.codex/skills/.system/openai-docs/SKILL.md), [plugin management](/root/.codex/plugins/cache/openai-curated-remote/plugin-management/0.1.0/skills/plugin-management/SKILL.md), and [Sites, local-only workflow](/root/.codex/plugins/cache/openai-curated-remote/sites/1.1.4/skills/sites/SKILL.md). No Sites hosting deployment was created.

## Proactive conversations and images — latest owner correction, 2026-11-09 India

Ji Eun can reach out first about important messages, schedule changes, personal/research developments, useful follow-ups, or a natural casual conversation. The owner explicitly removed proactive quiet-hour restrictions, cooldowns, quotas and a fixed message frequency. There is no requirement to send a message just because a check ran. Source-event deduplication and stale-alert expiry remain enforced in code. Explicit reminders and the 09:00 brief keep their separate settings.

The background source-refresh job `28dd0ad764ff` checks hourly at minute 15 around the clock, using Luna. This is the polling interval, not a prescribed conversation cadence or a real-time webhook. Existing subscription limits still apply; there is no paid inference fallback. Contextual outreach may also occur during other authorized work through `personal.notify_owner`. Updates cite a verified source link; casual starters can refer to the owner's invitation. Actual delivery uses the durable owner-only Discord outbox, supports verified public HTTPS image embeds, and preserves nonce/retry handling. No test DM was sent while developing this change; notification behavior was tested with mocked delivery.

For direct image replies, Hermes converts `MEDIA:/absolute/path/to/image.png` into a native Discord attachment. Roles are instructed to use workspace images, charts or attributed figures, and to keep transport markers out of ordinary prose. One actual 1024×1024 PNG upload succeeded in the private agent-activity channel (message 1569066826095403109). No new image-generation API or voice service was enabled.

Follow-up sources: `enable-context.py` applies read-only app permissions; `configure-proactive.py` configures the background job; `relax-proactive.py` applies the owner's final anytime/no-quota policy. When rerunning configuration, retain this final correction. The original broad auto-enabled Notion/Slack proposal was rejected by automatic review and replaced by explicit read-only allowlists. No remaining approval is needed for the deployed read-only context setup.


## Research SSH and Ji An — 2026-11-09

Ji An is installed as the Sol scientific interpretation specialist in both Hermes (`ji-an`) and native Codex roles. Ji An also has her own Discord bot, sharing the memory broker, task board, research access and Codex subscription with Ji Eun. Her supported standalone gateway serves only `ji-an`; Ji Eun owns the other profiles and the single global task dispatcher. Only Ji Eun runs the daily brief and proactive schedules. Bot messages cannot initiate work, preventing reply loops. All roles retain the existing bounded teammate/handoff behavior, topic/time-scoped memory and natural Discord style. Use Ji An for hypotheses, uncertainty, statistics, limitations and reproducibility, with primary evidence and actual artifact paths.

The isolated `personal-agent-research` service owns its own home, workforce login and SSH key. It exposes a peer-checked Unix broker; the regular assistant cannot read its credential directory. Google Cloud CLI 592.0.0 was installed from Google's official archive after checking its published SHA256. Profile `researcher-invoker-srinitish`, project `avid-renderer-503311-n6`, pool `lossfunk-researchers`, owner email `srinitishsri@gmail.com` (AWS emits a capital S). The public server host keys were supplied from the owner's trusted Mac and strict SSH host-key verification remains enabled. No Mac private keys or cloud credential files were copied.

| Server | Zone | Verification |
|---|---|---|
| petase-design | us-central1-c | GCP instance ID matched; SSH works as srinitish_srinivasan; existing Codex subscription login verified |
| agent-simulation-sandbox-nitish | us-central1-a | GCP instance ID matched; VM is stopped; public host key imported, live SSH verification pending until it runs |

Only these two owner-provided instances are allowlisted. The read-only project inventory contained other people's VMs; those were not added. The Mahesh guide is an example, not an identity or target to use. No VM was started, created or rebooted and no GPU driver was installed. Project folders visible in the owner's petase account are `~/kinharvest` and `~/UniKP`; no source or result files were imported during setup.

MCP tools: `research_status`, `research_probe`, `research_submit`, `research_task`, `research_retry`, `research_cancel`. Explicit owner-request evidence, a stable idempotency key and a specific project directory are required to submit work. Remote Codex uses the already authenticated subscription and Luna/Terra/Sol. `engine=command` executes an exact task-scoped script for the local Codex teammate. `engine=claude` requires a separate existing Claude subscription login; there is no paid API fallback. Claude Code 2.1.319 was installed in the SSH owner's account from Anthropic's official native npm package with SHA512 integrity verification; the owner explicitly deferred Claude on 2026-11-09. No Claude sign-in or use should be requested until the owner resumes it.

Jobs survive SSH disconnects, have bounded wall-clock limits (1–1440 minutes), and are idempotent across retries. Two research jobs may be outstanding concurrently. Disconnected jobs stop automatic connection attempts after three failures and remain unconfirmed; `research_retry` reconnects the same ID. Cancellation checks the remote process identity, targets only that job's process group, and covers the startup race. Keep experimental commands in the foreground under the runner. Native CLI reasoning/thinking blocks are excluded from the monitor. The monitor keeps the latest 120 visible remote events per task. Role descriptions and depth/handoff limits remain instructions, not a kernel security boundary.

Research tasks, host states, auth availability and clickable logs are in the private server dashboard and terminal monitor; plain lifecycle notices appear in the existing Discord activity channel. Normal requested jobs also queue owner-only completion/error/time-limit/connection-loss alerts with event deduplication and expiry. Connection checks were silent. A completion alert means the runner finished; Ji An must inspect actual results before claiming scientific success.

Workforce sign-in expires after about eight hours. Renew in THIS SERVER'S terminal:

```sh
sudo personal-agent-research-setup login
```

The helper prints a remote-bootstrap command to run on the Mac. Paste the returned result only into the server terminal. It verifies the owner workforce pool/subject before use. Do not send auth codes through Discord. Read status with `sudo personal-agent-research-setup status`; `probe HOST` performs a real read-only SSH check, and `inventory` lists cloud VMs without adding targets.

Claude Code is deferred by the owner. Only after the owner explicitly resumes it, sign in from the Mac using an existing Claude subscription:

```sh
ssh -t petase-design '~/.local/bin/claude auth login'
```

The research task database is included in encrypted state backups; GCP credentials and SSH keys are excluded. Remote project data/artifacts are not backed up by this assistant. Full stop suspends research dispatch and polling, preserving remote jobs; requested individual cancellation requires a live broker/SSH connection.

Validation: the complete suite passes 43 tests. A real remote command and Luna Codex task completed with the expected connection-check output and visible logs. Ji An's Sol profile called the actual research MCP successfully through Hermes/Codex. Dashboard API research status/logs were checked with authentication. No scientific experiment or project edit was performed.


## Discord SSH routing and Ji An gateway — 2026-11-09

The old conversational session tried a local SSH alias rather than the separate research broker. Live profile `agent.system_prompt` overlays now forward the current persona/routing into native Codex turns; stored prompts were refreshed without erasing chat history. MCP discovery also supplies the research connection workflow. Research MCP calls use a 130-second broker deadline instead of the 10-second memory deadline. A real check through the preserved Discord conversation reached petase-design after approximately 13.5 seconds, and both gateways were reloaded while idle.

Ji An bot `1569254077571797023` is connected in the owner's guild. Its root-only token is supplied by systemd credentials, separate from Ji Eun's. `sudo personal-agent-add-jian` is the hidden-token setup helper; it supports finishing an existing setup without asking for the token again. `gateway.standalone: true` prevents the primary multiplexed gateway from claiming Ji An's Discord profile. Global owner pause/resume and stop/start cover both bots. The monitor includes Ji An's service and identifies native root sessions from actual Hermes ownership.

Shared task `t_eb86cfc5` was dispatched by Ji Eun's gateway, admitted by Ji An's gateway, completed by her Sol worker, and left an addressed handoff comment for Ji Eun. The authenticated dashboard showed both services active and the completed card/logs. This setup check performed no experiments or project edits. Claude remains deferred. The simulation VM is stopped; the assistant does not start it merely to test SSH. Expired GCP sessions still need interactive renewal in the server console.


## WhatsApp Message yourself — 2026-11-09

The owner requested WhatsApp alongside Discord, first chose a separate bot number, then explicitly switched to the existing personal account using Message yourself. No phone number was purchased or registered. Hermes's bundled Baileys bridge is an unofficial WhatsApp Web linked device; protocol changes/account restrictions remain possible. Official guide: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp . No Meta Business API, webhook or paid provider was enabled.

Installed Node.js 22.23.4 from the official archive with its published SHA256 checked; manifest `node-runtime.json`. The pinned Hermes bridge was copied to `/opt/personal-agents/whatsapp-bridge`, with 143 locked dependencies built under the unprivileged service user using `--ignore-scripts`. The installed bridge/dependencies are root-owned. No Hermes vendor code was changed. `install-whatsapp.py` installs this integration; initial user pairing remains separate.

In this server's interactive terminal run:

```sh
sudo personal-agent-whatsapp-setup
```

Enter the existing personal number with country code at the hidden prompt, then scan the terminal QR using WhatsApp → Settings → Linked Devices → Link a Device. Never paste the QR, device keys or confirmation codes into chat. The helper verifies the linked account matches the supplied owner number before enabling WhatsApp. `--finish` completes an already paired setup without asking for the number again. It waits for active Discord work to finish before restarting only Ji Eun's gateway. No separate daemon/schedules are duplicated. The helper verifies a connected bridge health response; a real inbound chat and outbound reminder still require checking after pairing.

Only Ji Eun/default owns the device; all specialist profiles have WhatsApp disabled, including Ji An. Session keys stay in `/var/lib/personal-agent/.hermes/whatsapp/session` with private permissions and are excluded from shared memory/backups. The bridge listens on loopback port 3000; there is no public webhook. Incoming self-chat only, owner-only sender/admin allowlists, groups disabled, strangers ignored, read receipts off and debug logging off. A short `Ji Eun:` prefix plus upstream outbound-ID tracking prevents self-chat reply loops. STT remains explicitly disabled and voice remains off.

Structured memory and task handoffs are shared across Discord/WhatsApp. Reminder and proactive MCP tools accept `delivery_channel=whatsapp`; existing records/default delivery stay Discord. Requests made in WhatsApp should select WhatsApp unless the owner names another channel. Deliveries target only the verified owner JID from protected data-service metadata; agents cannot choose arbitrary recipients through this outbox. Known pre-send disconnects retry after reconnection; a POST whose outcome is unconfirmed stays ambiguous for reconciliation, preventing blind duplicates. Recurring reminders preserve their selected channel, and snooze/cancel uses the same shared records. The daily brief stays on its existing Discord schedule until changed by the owner. Meetups/deadlines should distinguish tentative proposals, agreed times and calendar entries, with source/time/confidence and reschedule corrections.

The owner also wants selected chat/group context, but has not named those conversations yet. That ingestion is NOT enabled by self-chat pairing; do not claim other WhatsApp conversations/history are being monitored or open group policies. It needs explicit scope and a suitable read-only ingestion route. Forwarding relevant messages into Message yourself is supported immediately after pairing.

The server dashboard and Discord operations panel show credential-free WhatsApp state, and delivery logs include the actual selected channel. Validation: 52 Python integration tests pass, including channel isolation, old-schema migration, offline recovery, wrong-session refusal, fixed owner recipient and ambiguous-send non-replay. Nineteen upstream bridge allowlist/owner/echo tests pass as the service identity. Phone pairing is complete and owner-only outbound delivery was verified on 2026-11-09. The gateway and private monitor report connected. A real owner-typed inbound conversation remains to be exercised.


Pairing follow-up: Baileys 7.0.0-rc13 omitted the registration-refresh handler and dereferenced an absent account identity while acknowledging pre-login notifications. A minimal reviewed JS backport of upstream PR 2765 (head `042fe1f3ddacf63ac2288837fbc8a395556bbb6e`, still unmerged) is applied only to the isolated bridge dependency. Reproducible source: `patch-whatsapp-pairing.py`, `whatsapp-pairing-compat.mjs`, manifest with original/patched SHA256s. Four targeted protocol tests pass. No Hermes vendor core patch, fork replacement or blanket dependency update was applied. The install helper records the exact supported package-hash readiness stamp, so the read-only gateway uses the prepared dependencies rather than attempting to install them again.

The owner completed QR linking, verified to match the number entered privately. Baileys QR pairing saves a signed account and `me` while leaving the legacy `registered` flag false; the helper now checks those actual completed-pairing fields. Two regression tests cover that distinction. `--retry` reuses the previously entered number; `--finish` activates an already linked account. One owner-authorized connection message traversed the durable WhatsApp outbox successfully (ID `fda6666a929f4149a4165ebd`, sent 2026-11-09T18:00:39Z). An acknowledged send is not proof the owner read it. Discord and all existing services remained active. WhatsApp history/selected-group ingestion remains disabled.


Model preference — confirmed 2026-11-10 India time: Ji Eun may use Luna/Terra; her main default is `gpt-6-luna` and the everyday role is `gpt-6.1-terra`. Ji An’s main conversation and scientific interpretation must use `gpt-6.1-sol`, including her separate Discord profile and native Codex role. Existing live defaults and recent native/session metadata were verified to match. No silent downgrade or paid API fallback is configured.


## Application self-maintenance (2026-11-11)

The owner authorized Ji Eun and Ji An to inspect, fix and extend their code. The scoped maintenance MCP, immutable candidate checks, peer review, transactional deploy/rollback and recovery are installed. See [SELF-MAINTENANCE.md](../SELF-MAINTENANCE.md). The private mission-control dashboard includes candidate logs and release state. Owner full stop writes a root-controlled marker respected by maintenance. General sudo, credentials, service policy and root-run scripts remain outside application self-deployment. The latency proposal remains unapproved.
