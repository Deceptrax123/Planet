"""Credential-free client for the narrowly scoped maintenance service."""
import json
import socket

SOCKET = '/run/personal-agent-maintenance/broker.sock'


def request(method, args=None, timeout=15):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(SOCKET)
        client.sendall(json.dumps({'method':method,'args':args or {}},allow_nan=False).encode()+b'\n')
        with client.makefile('rb') as stream:
            raw=stream.readline(5_000_001)
    if len(raw)>5_000_000:raise ValueError('Maintenance response too large')
    result=json.loads(raw)
    if 'error' in result:raise ValueError(result['error'])
    return result['result']
