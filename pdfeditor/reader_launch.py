"""Blocking launch forwarding without loading Qt widgets or document modules."""

import hashlib
import json
import os
import sys
import time

from PyQt5.QtNetwork import QLocalSocket

from . import settings

MAX_REQUEST_BYTES = 32768


def server_name():
    # Keep the existing per-user, per-installation endpoint identity.
    identity = os.path.abspath(settings.PATH) + "|" + os.path.abspath(sys.executable)
    return "spdf-reader-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def forward_to_resident(path=None):
    """Return only after the resident acknowledges the request, or fall back."""
    request = json.dumps({"path": os.path.abspath(path) if path else None}).encode("utf-8") + b"\n"
    if len(request) > MAX_REQUEST_BYTES:
        return False
    socket = QLocalSocket()
    try:
        socket.connectToServer(server_name())
        if not socket.waitForConnected(200):
            return False
        if socket.write(request) != len(request):
            return False
        socket.flush()
        if socket.bytesToWrite() and not socket.waitForBytesWritten(200):
            return False
        received = bytearray()
        deadline = time.monotonic() + .8
        while len(received) < MAX_REQUEST_BYTES:
            received.extend(bytes(socket.readAll()))
            if b"\n" in received:
                return bytes(received).split(b"\n", 1)[0] == b"OK"
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not remaining or not socket.waitForReadyRead(remaining):
                # A peer may disconnect immediately after its final write.
                received.extend(bytes(socket.readAll()))
                return bytes(received).split(b"\n", 1)[0] == b"OK" and b"\n" in received
        return False
    finally:
        socket.abort()
