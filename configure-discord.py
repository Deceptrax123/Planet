#!/usr/bin/env python3
"""Configure Discord without placing the bot token in chat or shell history."""
import getpass
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse
import urllib.request

OWNER = "562571259758772254"
DEST = Path("/root/.config/personal-agents/discord.json")


def main():
    if not os.isatty(0):
        raise SystemExit("Run this command in your interactive server terminal; input is hidden.")
    token = getpass.getpass("Discord Bot token (hidden): ").strip()
    if not token or any(c.isspace() for c in token):
        raise SystemExit("Expected one bot token without whitespace.")
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": "Bot " + token, "User-Agent": "PersonalAssistantSetup/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            bot = json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Discord rejected the token (HTTP {exc.code}); nothing saved.") from None
    except OSError:
        raise SystemExit("Could not reach Discord; nothing saved. Check server networking.") from None
    if bot.get("bot") is not True:
        raise SystemExit("This is not a bot account; nothing saved.")
    DEST.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DEST.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".discord-", dir=DEST.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump({"bot_token": token, "bot_id": bot["id"], "owner_id": OWNER}, stream)
        stream.write("\n")
    os.replace(temporary, DEST)
    params = urllib.parse.urlencode({"client_id": bot["id"], "permissions": "309237763136", "scope": "bot applications.commands"})
    print(f"Saved securely for bot {bot.get('username', bot['id'])}. The token was not printed.")
    print("Invite it to your private Discord server using:")
    print("https://discord.com/oauth2/authorize?" + params)
    print("Message Content Intent must be enabled. No voice permissions are requested.")


if __name__ == "__main__":
    main()
