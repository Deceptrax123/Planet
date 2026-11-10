#!/usr/bin/env python3
"""Owner's server-side terminal monitor; no model calls, keys, or provider requests."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from assistant_broker import request


def snapshot():
    data = request("assistant_status")
    data["paused"] = Path('/var/lib/personal-agent/.hermes/ESTOP').exists()
    data["services"] = {}
    services=["gateway", "data", "reminders", "mission-control", "discord-monitor", "research"]
    if Path('/var/lib/personal-agent/.config/ji-an-discord.json').exists():services.append('ji-an')
    for name in services:
        result = subprocess.run(["systemctl", "is-active", "personal-agent-" + name], capture_output=True, text=True, timeout=3)
        data["services"][name] = result.stdout.strip()
    path = Path("/var/lib/personal-agent/.hermes/kanban.db")
    data["board"] = []
    if path.is_file():
        try:
            db = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            columns = {r[1] for r in db.execute("PRAGMA table_info(tasks)")}
            wanted = [c for c in ["id", "title", "assignee", "status", "model_override", "updated_at", "created_at", "session_id", "last_failure_error"] if c in columns]
            if wanted:
                order = "updated_at" if "updated_at" in columns else "created_at"
                data["board"] = [dict(r) for r in db.execute("SELECT " + ",".join(wanted) + " FROM tasks ORDER BY " + order + " DESC LIMIT 30")]
                for row in data["board"]:
                    row["parents"] = [r[0] for r in db.execute("SELECT parent_id FROM task_links WHERE child_id=?", (row["id"],))]
            db.close()
        except sqlite3.Error:
            data["board_error"] = "Task board is busy or still initializing"
    data["schedules"] = []
    try:
        jobs = json.loads(Path('/var/lib/personal-agent/.hermes/cron/jobs.json').read_text()).get('jobs', [])
        data["schedules"] = [{k: job.get(k) for k in ['id', 'name', 'enabled', 'state', 'next_run_at', 'last_run_at', 'last_status', 'last_error', 'last_delivery_error']} for job in jobs]
    except (OSError, ValueError):
        data["schedule_error"] = 'Schedule metadata unavailable'
    try:
        data['research'] = request('research_status', timeout=15)
    except (OSError, ValueError):
        data['research'] = {'auth':'unavailable', 'hosts':[], 'tasks':[]}
    return data


def render(data):
    lines = ["PERSONAL AGENT TEAM — " + data["at"], "  ".join(f"{k}: {v}" for k, v in data["services"].items()),
             "Ji Eun mission control: http://127.0.0.1:9120 | India time | proactive conversations anytime", "", "AGENT / STATE / MODEL / TASK / LATEST ACTIVITY"]
    for row in data["activities"]:
        lines.append(f"{row['agent'][:18]:18} {row['state'][:8]:8} {row['model'][:16]:16} {row['task_id'][:16]:16} {row['summary'][:100]}")
    if not data["activities"]:
        lines.append("No work has started yet. Idle agents do not make model calls.")
    lines.extend(["", "DURABLE TASK BOARD"])
    for row in data["board"]:
        lines.append(f"{row.get('id','')[:16]:16} {row.get('assignee','') or 'unassigned':16} {row.get('status',''):10} {row.get('title','')[:90]}")
    lines.extend(["", "WHATSAPP: " + json.dumps(data.get("whatsapp",{})), "REMINDERS: " + json.dumps(data["reminders"]), "RECENT DELIVERIES"])
    for row in data["deliveries"][:8]:
        lines.append(f"{row['id']}  {row['status']}  {row.get('last_error') or ''}")
    research = data.get('research', {})
    lines.extend(['', 'RESEARCH SERVERS — '+research.get('auth','unknown')])
    for host in research.get('hosts',[]):
        lines.append(host['name']+'  '+host.get('state','not yet verified'))
    for task in research.get('tasks',[]):
        lines.append(task['id']+'  '+task['state']+'  '+task['host']+'  '+task['engine']+'  '+task['title'])
    lines.extend(["", "Controls: personal-agent-control pause | resume | stop | start | status", "Live service log: journalctl -u personal-agent-gateway -f"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            data = snapshot()
            output = json.dumps(data, indent=2) if args.json else render(data)
        except (OSError, ValueError) as exc:
            output = "Monitor could not reach the data service: " + str(exc)
        if args.watch and sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
        print(output, flush=True)
        if not args.watch:
            break
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
