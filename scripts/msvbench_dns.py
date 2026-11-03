"""Opt-in process-local DNS fallback. TLS hostname verification stays enabled."""
import json
import os
import socket
import time
from pathlib import Path


def install():
    filename = os.environ.get('MSVBENCH_DNS_FALLBACK')
    if not filename or getattr(socket.getaddrinfo, '_msvbench_fallback', False):
        return
    data = json.loads(Path(filename).read_text())
    original = socket.getaddrinfo
    counters = {}

    def resolve(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return original(host, port, family, type, proto, flags)
        except socket.gaierror:
            if time.time() > data['expires_at'] or host not in data['hosts']:
                raise
            addresses = data['hosts'][host]
            index = counters.get(host, 0)
            counters[host] = index + 1
            ip = addresses[index % len(addresses)]
            return original(ip, port, family, type, proto, flags)

    resolve._msvbench_fallback = True
    socket.getaddrinfo = resolve
