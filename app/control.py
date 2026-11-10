#!/usr/bin/env python3
"""Explicit owner controls. Agents cannot call privileged service management."""
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path


def main():
    if os.getuid() != 0:
        raise SystemExit("Run this command as the server administrator.")
    user = pwd.getpwnam("personal-agent")
    base = ["runuser", "-u", "personal-agent", "--", "env", "-i", "HOME=" + user.pw_dir,
            "USER=personal-agent", "LOGNAME=personal-agent", "CODEX_HOME=" + user.pw_dir + "/codex",
            "PATH=/var/lib/personal-agent/.local/bin:/opt/personal-agents/bin:/usr/bin:/bin",
            "XDG_RUNTIME_DIR=/run/user/" + str(user.pw_uid),
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + str(user.pw_uid) + "/bus", "LANG=C.UTF-8"]
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    hermes = base + ["/var/lib/personal-agent/.local/bin/hermes"]
    ji_an = Path('/etc/personal-agents/ji-an-discord.token').exists()
    if action in {"pause", "resume"}:
        subprocess.run(hermes + [action], cwd=user.pw_dir, check=True)
        if ji_an:subprocess.run(hermes+['--profile','ji-an',action],cwd=user.pw_dir,check=True)
    elif action == "stop":
        subprocess.run(["systemctl", "stop", "personal-agent-gateway", "personal-agent-reminders", "personal-agent-research"]+(['personal-agent-ji-an'] if ji_an else []), check=True)
        result = subprocess.run(base + ["systemctl", "--user", "list-units", "--type=scope", "--no-legend", "--plain", "hermes-worker-kanban-*", "hermes-worker-cron-*"], capture_output=True, text=True, check=True)
        scopes = [line.split()[0] for line in result.stdout.splitlines() if line.split() and re.fullmatch(r"hermes-worker-(?:kanban|cron)-[A-Za-z0-9_.@\\:-]+\.scope", line.split()[0])]
        if scopes:
            subprocess.run(base + ["systemctl", "--user", "stop", *scopes], check=True)
        print("Gateway, reminder sends, managed workers and new research dispatch stopped. Monitor remains available. Remote jobs keep running until individually cancelled.")
    elif action == "start":
        subprocess.run(["systemctl", "start", "personal-agent-gateway", "personal-agent-reminders", "personal-agent-monitor", "personal-agent-research"]+(['personal-agent-ji-an'] if ji_an else []), check=True)
    elif action == "status":
        subprocess.run(["/usr/bin/python3", "/opt/personal-agents/app/monitor.py"], check=True)
    elif action == "monitor-password":
        if not sys.stdout.isatty():
            raise SystemExit("Display the dashboard password in your interactive server terminal.")
        print("Username: ji-eun\nPassword: " + Path("/etc/personal-agents/monitor.password").read_text().strip())
    elif action == "task" and len(sys.argv) > 2:
        task = sys.argv[2]
        if not re.fullmatch(r"t_[a-f0-9]{8,32}", task):
            raise SystemExit("Invalid task ID")
        subprocess.run(hermes + ["kanban", "show", task], cwd=user.pw_dir, check=True)
    else:
        raise SystemExit("Usage: personal-agent-control pause|resume|stop|start|status|task TASK_ID")


if __name__ == "__main__":
    main()
