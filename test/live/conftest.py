import shutil

import pytest

from test.live.two_endpoint_bus import TwoEndpointBus


@pytest.fixture
def two_endpoint_bus():
    """A live messagebus with a factory for connected endpoints; torn down by
    recorded PID. Skips if the ovos-messagebus binary is not on PATH."""
    binary = shutil.which("ovos-messagebus")
    if not binary:
        pytest.skip("ovos-messagebus not on PATH")
    bus = TwoEndpointBus(binary)
    try:
        yield bus
    finally:
        bus.close()
