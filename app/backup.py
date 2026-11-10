#!/usr/bin/env python3
"""Consistent encrypted state backups; credentials are excluded."""
from datetime import datetime, timezone
import os
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tarfile
import tempfile


def main():
    if os.getuid() != 0:
        raise SystemExit("Backup requires the server administrator.")
    output = Path("/var/backups/personal-agents")
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    output.chmod(0o700)
    key = Path("/etc/personal-agents/backup.key")
    if not key.exists():
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48) + "\n")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = output / ("state-" + stamp + ".tar.gz.enc")
    with tempfile.TemporaryDirectory(prefix="personal-agent-backup-") as temporary:
        directory = Path(temporary)
        archive = directory / "state.tar.gz"
        snapshots = directory / "sqlite"
        snapshots.mkdir()
        candidates = [Path("/var/lib/personal-agent-data/assistant.sqlite")]
        candidates.append(Path('/var/lib/personal-agent-research/state/research.sqlite'))
        candidates += list(Path("/var/lib/personal-agent/.hermes").glob("**/*.db"))
        with tarfile.open(archive, "w:gz") as tar:
            for i, path in enumerate(candidates):
                if not path.is_file():
                    continue
                snapshot = snapshots / f"{i}.sqlite"
                source = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=10)
                destination = sqlite3.connect(snapshot)
                try:
                    source.backup(destination)
                finally:
                    source.close()
                    destination.close()
                tar.add(snapshot, arcname="sqlite" + str(path))
            for path in Path("/root/shared-memory").rglob("*"):
                if path.is_file() and path.suffix in {".md", ".json", ".py", ".cron"}:
                    tar.add(path, arcname="shared-memory/" + str(path.relative_to("/root/shared-memory")))
            for path in Path("/var/lib/personal-agent/.hermes").glob("**/SOUL.md"):
                tar.add(path, arcname="hermes/" + str(path.relative_to("/var/lib/personal-agent/.hermes")))
            tar.add("/var/lib/personal-agent-data/exports", arcname="dynamic-memory-export")
        result = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt",
                                 "-in", str(archive), "-out", str(final), "-pass", "file:" + str(key)], capture_output=True)
        if result.returncode:
            final.unlink(missing_ok=True)
            raise SystemExit("Backup encryption failed")
        final.chmod(0o600)
        signature = hmac.new(key.read_bytes(), final.read_bytes(), hashlib.sha256).hexdigest()
        signature_path = final.with_suffix(final.suffix + '.hmac')
        signature_path.write_text(signature + '\n')
        signature_path.chmod(0o600)
        # Verify decryption and archive readability without restoring over live state.
        check = directory / "check.tar.gz"
        subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-in", str(final),
                        "-out", str(check), "-pass", "file:" + str(key)], check=True, capture_output=True)
        if not hmac.compare_digest(signature_path.read_text().strip(), hmac.new(key.read_bytes(), final.read_bytes(), hashlib.sha256).hexdigest()):
            raise SystemExit('Backup authentication failed')
        with tarfile.open(check) as tar:
            names = tar.getnames()
            for index, member in enumerate(tar.getmembers()):
                if member.isfile() and member.name.startswith('sqlite/'):
                    restored = directory / ('restored-' + str(index) + '.sqlite')
                    with tar.extractfile(member) as stream:
                        restored.write_bytes(stream.read())
                    with sqlite3.connect(restored) as db:
                        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise SystemExit('Restored database integrity check failed')
            if not any(name.endswith("assistant.sqlite") for name in names):
                raise SystemExit("Backup verification failed: missing assistant state")
        for old in sorted(output.glob("state-*.tar.gz.enc"))[:-14]:
            old.unlink()
            old.with_suffix(old.suffix + '.hmac').unlink(missing_ok=True)
    print("Encrypted backup and isolated database restore checks completed:", final)
    print("Keep /etc/personal-agents/backup.key separately protected for recovery.")


if __name__ == "__main__":
    main()
