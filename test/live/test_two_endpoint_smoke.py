"""Smoke test: the fixture delivers a message from one endpoint to another over
the real wire."""
import time

from ovos_bus_client.message import Message


def test_message_crosses_between_two_endpoints(two_endpoint_bus):
    sub = two_endpoint_bus.endpoint()
    emit = two_endpoint_bus.endpoint()
    seen = []
    sub.on("two.endpoint.smoke", lambda m: seen.append(m.data.get("n")))
    time.sleep(0.5)
    emit.emit(Message("two.endpoint.smoke", {"n": 42}))
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.1)
    assert seen == [42], f"expected [42], got {seen}"
