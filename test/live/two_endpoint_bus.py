"""A real two-endpoint messagebus fixture.

Stands up a live ``ovos-messagebus`` on a unique free port with a private XDG
config, and hands out connected ``MessageBusClient`` endpoints, for tests that
need two independent clients on one wire: receive-side counterpart delivery,
the dual-emit mirror, cross-vintage behaviour. The broker is torn down by the
PID recorded at spawn, never by pattern, so it cannot reach another session's
services. Ports are OS-assigned, so parallel tests never collide on a fixed one.
"""
import contextlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TwoEndpointBus:
    """A live messagebus plus a factory for connected client endpoints."""

    def __init__(self, messagebus_bin: str, route: str = "/core"):
        self.port = _free_port()
        self.route = route
        self._xdg = Path(tempfile.mkdtemp(prefix="twoep-bus-"))
        conf_dir = self._xdg / "mycroft"
        conf_dir.mkdir(parents=True)
        (conf_dir / "mycroft.conf").write_text(json.dumps(
            {"websocket": {"host": "127.0.0.1", "port": self.port,
                           "route": route, "ssl": False}}))
        env = {**os.environ, "XDG_CONFIG_HOME": str(self._xdg)}
        self._proc = subprocess.Popen(
            [messagebus_bin], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._clients = []
        self._await_listening()

    def _await_listening(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("messagebus exited before it listened")
            with contextlib.closing(socket.socket()) as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.2)
        raise RuntimeError(f"messagebus did not listen on port {self.port}")

    def endpoint(self):
        """A connected MessageBusClient on this bus. Uses whatever
        ovos-bus-client is importable in the current interpreter."""
        from ovos_bus_client import MessageBusClient
        bus = MessageBusClient(host="127.0.0.1", port=self.port, route=self.route)
        bus.run_in_thread()
        if not bus.connected_event.wait(10):
            raise RuntimeError("endpoint could not connect to the messagebus")
        self._clients.append(bus)
        return bus

    def close(self) -> None:
        for client in self._clients:
            with contextlib.suppress(Exception):
                client.close()
        with contextlib.suppress(Exception):
            self._proc.terminate()
            self._proc.wait(timeout=5)
        with contextlib.suppress(Exception):
            self._proc.kill()
        shutil.rmtree(self._xdg, ignore_errors=True)
