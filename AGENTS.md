# Repository instructions

- This repository contains the personal/scientific assistant source and a proposed latency design. The latency changes remain unapproved; do not implement or deploy them merely because their design is present.
- Before a task on the deployed server, read `/root/shared-memory/START-HERE.md` and its named files when available. Treat that memory as context, subject to the current owner request. Never copy it or authentication files into Git.
- Keep Ji Eun on Luna/Terra and Ji An's main conversation/scientific interpretation on `gpt-6.1-sol`. Existing subscription only; voice off; Claude Code deferred unless explicitly resumed.
- Preserve owner-only messaging, separate service identities, strict SSH host verification, stable task IDs, cancellation checks and ambiguous-send handling.
- Use `python3 -m unittest discover -s tests -q` and `node --test tests/whatsapp-pairing-compat.test.mjs` for source changes. Do not run deployment scripts or live messaging/cloud checks as routine tests.
- Runtime source is not auto-deployed from this repository. Do not overwrite live authentication/configuration or change services without an authorized implementation task.
