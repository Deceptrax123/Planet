"""Root-controlled, credential-free bridge between portable and runtime memory."""
import json
import os
from pathlib import Path
import pwd
import tempfile


def atomic(path, data, mode, uid=0, gid=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(name, mode)
        os.chown(name, uid, gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    group = pwd.getpwnam("personal-agent-data").pw_gid
    directory = Path("/var/lib/personal-agent-data/shared-snapshot")
    directory.mkdir(exist_ok=True)
    os.chown(directory, 0, group)
    directory.chmod(0o750)
    source = Path("/root/shared-memory/records.json")
    atomic(directory / "records.json", json.loads(source.read_text()), 0o640, gid=group)
    export = Path("/var/lib/personal-agent-data/exports/memory.json")
    if export.exists():
        atomic(Path("/root/shared-memory/personal-agents/memory.json"), json.loads(export.read_text()), 0o600)


if __name__ == "__main__":
    main()
