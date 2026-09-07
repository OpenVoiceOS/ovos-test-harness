"""One scheduler, two protocols: the ``mycroft.scheduler.*`` topics a skill
built years ago still emits, and the ``ovos.scheduler.*`` request/response
pairs SCHEDULER-1 defines.

The scheduler is where a broken migration is loudest, because the owner of a
schedule is usually not running when the schedule was made: an alarm skill
that re-creates its events on every boot over the legacy topics has to keep
ringing on a stack whose scheduler only speaks the specified protocol, and it
has to be able to cancel what it created. Both directions are asserted against
the same live service on one bus, so a divergence between the two protocols
shows up as one of these cells rather than as a silent alarm.

Legacy identity is the subtle half. The old skill framework named an event it
was given no name for after the handler it bound, as ``<skill_id>:<handler>``,
and that string is the only handle a skill has when it later wants to cancel.
The service therefore has to key a legacy schedule by exactly that name, and
replace rather than append when the same name arrives again.

The scheduler ships in ovos-bus-client#311 and is not on PyPI, so these cells
run wherever that branch is installed, selected by ``OVOS_SCHEDULER_CELLS``
— never by importability, so a broken install fails here instead of skipping
quietly.
"""
import os
import tempfile
import time

import pytest
from ovos_bus_client.message import Message

SCHEDULER_CELLS = os.environ.get("OVOS_SCHEDULER_CELLS") == "1"

pytestmark = pytest.mark.skipif(
    not SCHEDULER_CELLS,
    reason="the scheduler cells run in the job that installs the "
           "ovos-bus-client scheduler service (set OVOS_SCHEDULER_CELLS=1)")

if SCHEDULER_CELLS:
    from ovos_bus_client.util.scheduled_events import topics
    from ovos_bus_client.util.scheduled_events.service import ScheduledEventService

#: what the old skill framework calls an event it was given no name for
LEGACY_EVENT = "migration.probe.skill:on_probe"
SPEC_OWNER = "migration.probe.skill"
SPEC_EVENT = f"{SPEC_OWNER}.probe"

#: short enough to see several occurrences, long enough not to race the store
PERIOD = 0.5
SETTLE = 0.4


@pytest.fixture
def scheduler():
    """A live scheduler on a bus, with its store in a throwaway directory."""
    from ovos_utils.fakebus import FakeBus
    from ovos_utils.log import LOG
    LOG.set_level("ERROR")
    bus = FakeBus()
    with tempfile.TemporaryDirectory() as store:
        service = ScheduledEventService(
            bus, store_path=os.path.join(store, "schedule.json"))
        try:
            yield bus, service
        finally:
            service.shutdown()


def _collect(bus, topic):
    received = []
    bus.on(topic, received.append)
    return received


def test_legacy_schedule_fires_under_the_specified_service(scheduler):
    """A skill that still speaks the pre-spec protocol keeps being woken up."""
    bus, _ = scheduler
    fired = _collect(bus, LEGACY_EVENT)
    bus.emit(Message(topics.LEGACY_SCHEDULE,
                     {"event": LEGACY_EVENT, "time": time.time() + SETTLE,
                      "repeat": PERIOD, "data": {"probe": True}}))
    time.sleep(SETTLE + PERIOD * 2)
    assert fired, f"a {topics.LEGACY_SCHEDULE} request never fired {LEGACY_EVENT}"
    assert fired[0].data.get("probe") is True, (
        f"the fired event lost the payload it was scheduled with: {fired[0].data}")


def test_legacy_repeat_is_cancellable_by_its_handler_name(scheduler):
    """The ``<skill_id>:<handler>`` name is the only handle an unnamed repeat
    ever had, so removing under it must stop the schedule."""
    bus, _ = scheduler
    fired = _collect(bus, LEGACY_EVENT)
    bus.emit(Message(topics.LEGACY_SCHEDULE,
                     {"event": LEGACY_EVENT, "time": time.time(),
                      "repeat": PERIOD}))
    time.sleep(PERIOD * 2)
    assert fired, "the repeat never started, so cancelling it proves nothing"
    bus.emit(Message(topics.LEGACY_REMOVE, {"event": LEGACY_EVENT}))
    time.sleep(SETTLE)
    seen = len(fired)
    time.sleep(PERIOD * 3)
    assert len(fired) == seen, (
        f"{LEGACY_EVENT} fired {len(fired) - seen} more times after "
        f"{topics.LEGACY_REMOVE}")


def test_legacy_get_event_is_answered(scheduler):
    """``mycroft.scheduler.get_event`` still answers on the reply topic the
    old protocol listens to, describing the schedule it was asked about."""
    bus, _ = scheduler
    replies = _collect(bus, f"{topics.LEGACY_GET_REPLY_PREFIX}{LEGACY_EVENT}")
    bus.emit(Message(topics.LEGACY_SCHEDULE,
                     {"event": LEGACY_EVENT, "time": time.time() + 60,
                      "repeat": PERIOD}))
    bus.emit(Message(topics.LEGACY_GET, {"name": LEGACY_EVENT}))
    time.sleep(SETTLE)
    assert replies, f"{topics.LEGACY_GET} was never answered"
    answer = replies[0].data
    assert answer.get("event") == LEGACY_EVENT, answer
    entry = answer.get("schedule")
    assert entry and entry[0] > time.time(), (
        f"the answer describes no upcoming occurrence: {answer}")


def test_specified_schedule_cancel_get_round_trip(scheduler):
    """The specified protocol answers every request it accepts, and a cancelled
    schedule is gone from the store's view of the world."""
    bus, _ = scheduler
    scheduled = _collect(bus, topics.SCHEDULER_SCHEDULE_RESPONSE)
    got = _collect(bus, topics.SCHEDULER_GET_RESPONSE)
    cancelled = _collect(bus, topics.SCHEDULER_CANCEL_RESPONSE)
    fired = _collect(bus, SPEC_EVENT)

    request = {"id": SPEC_EVENT, "owner": SPEC_OWNER, "event": SPEC_EVENT,
               "every": {"seconds": PERIOD}}
    bus.emit(Message(topics.SCHEDULER_SCHEDULE, request))
    time.sleep(PERIOD * 2)
    assert scheduled and scheduled[0].data.get("ok") is True, (
        f"{topics.SCHEDULER_SCHEDULE} was refused or unanswered: "
        f"{[m.data for m in scheduled]}")
    assert fired, f"the accepted schedule never fired {SPEC_EVENT}"

    bus.emit(Message(topics.SCHEDULER_GET,
                     {"id": SPEC_EVENT, "owner": SPEC_OWNER}))
    time.sleep(SETTLE)
    assert got and got[0].data.get("existed") is True, (
        f"{topics.SCHEDULER_GET} does not know the schedule it accepted: "
        f"{[m.data for m in got]}")
    assert got[0].data["record"]["id"] == SPEC_EVENT, got[0].data

    bus.emit(Message(topics.SCHEDULER_CANCEL,
                     {"id": SPEC_EVENT, "owner": SPEC_OWNER}))
    time.sleep(SETTLE)
    assert cancelled and cancelled[0].data.get("existed") is True, (
        f"{topics.SCHEDULER_CANCEL} did not find the schedule: "
        f"{[m.data for m in cancelled]}")
    seen = len(fired)
    time.sleep(PERIOD * 3)
    assert len(fired) == seen, f"{SPEC_EVENT} fired after it was cancelled"


def test_a_legacy_name_scheduled_twice_is_replaced_not_doubled(scheduler):
    """A skill that re-creates its schedules on every boot must not end up
    with two of each — the one behaviour the specified store changes, and the
    reason an alarm used to ring twice."""
    bus, _ = scheduler
    fired = _collect(bus, LEGACY_EVENT)
    for _ in range(3):
        bus.emit(Message(topics.LEGACY_SCHEDULE,
                         {"event": LEGACY_EVENT, "time": time.time() + SETTLE}))
    time.sleep(SETTLE + PERIOD * 2)
    assert len(fired) == 1, (
        f"the same legacy event name scheduled three times fired "
        f"{len(fired)} times")
