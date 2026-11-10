"""Small diagnostic client for Codex's documented stdio JSON-RPC interface."""
import json
import os
import selectors
import subprocess
import time


class CodexRPC:
    def __init__(self, binary="/opt/personal-agents/bin/codex", cwd=None, env=None):
        self.process = subprocess.Popen([binary, "app-server", "--listen", "stdio://"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, cwd=cwd, env=env)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.sequence = 0
        self.notifications = []
        self.call("initialize", {"clientInfo": {"name": "personal-assistant-monitor", "version": "1.0.0"}, "capabilities": {"experimentalApi": True}})
        self.send({"method": "initialized", "params": {}})

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def read(self, timeout=30):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            if time.monotonic() >= deadline:
                raise TimeoutError("Codex app-server timed out")
            if not self.selector.select(min(1, max(0, deadline - time.monotonic()))):
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Codex app-server exited")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def call(self, method, params=None, timeout=60):
        self.sequence += 1
        identifier = self.sequence
        self.send({"id": identifier, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.read(max(0.1, deadline - time.monotonic()))
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"]))
                return message.get("result")
            self.notifications.append(message)
        raise TimeoutError("Codex app-server RPC timed out")

    def close(self):
        self.selector.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
