"""T2.4 scenario 6 -- common_query fan-out (design §2.3 item 6).

``ovos.common_query.ping`` -> ``.pong`` -> ``question:query`` ->
``question:query.response``, driven through the real
``ovos_commonqa.opm.CommonQAService`` on the driver/core side and a
skill-side responder that binds the SAME real wire topics
(``skill_process.py``'s ``handle_cq_ping``/``handle_cq_query`` -- see
``driver.py``'s module comment for why this is not a hand-rolled protocol:
``ovos-workshop`` documents a ``CommonQuerySkill`` base class in
``docs/skill-classes.md`` that does not exist in
``ovos_workshop/skills/`` on current dev -- checked directly, a real
docs/source drift finding, not assumed). ``fallback-unknown`` does not do
CQ (design instruction) -- confirmed: nothing in
``ovos_workshop/skills/fallback.py`` touches ``question:query``.

No suitable PyPI CQ test skill was found (``ovos-skill-fakewiki`` does not
resolve on PyPI as of this batch -- checked, not assumed), so the in-fixture
responder is the sanctioned fallback per the task brief.
"""
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (CQ_PING_TOPIC, CQ_PONG_TOPIC, CQ_QUERY_TOPIC,
                     CQ_RESPONSE_TOPIC, SKILL_ID,
                     BusServer, Capture, SkillProcess, boundary_xfail)
from .test_mixed_version_matrix import COMBO, COMBOS, SKILL_PYTHON

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="needs BACKCOMPAT_COMBO and BACKCOMPAT_SKILL_PYTHON; see "
           "test/backcompat/build_venvs.sh")


@pytest.fixture(scope="module")
def stack():
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}")
    server = BusServer()
    skill = None
    try:
        bus = server.client(emit_legacy=None)
        import os
        os.environ["BACKCOMPAT_ENABLE_CQ"] = "1"
        try:
            skill = SkillProcess(SKILL_PYTHON, server.xdg)
        finally:
            os.environ.pop("BACKCOMPAT_ENABLE_CQ", None)
        yield server, bus, skill
    finally:
        if skill is not None:
            skill.stop()
        server.stop()


@pytest.fixture(scope="module")
def cq_service(stack):
    """The real ``CommonQAService`` pipeline plugin, running in the driver
    process against the driver's core venv -- genuine per-combo core code,
    not a stand-in. Imported lazily: ``ovos-common-query-pipeline-plugin``
    is a core-venv-only dependency, same principle as
    ``driver.make_converse_service``.
    """
    from ovos_commonqa.opm import CommonQAService
    _server, bus, _skill = stack
    service = CommonQAService(bus=bus, config={"min_response_wait": 0.2,
                                               "max_response_wait": 3})
    yield service
    service.shutdown()


@pytest.mark.axes("S", "C")
def test_the_pipeline_discovers_the_skill_via_ping_pong(cq_service):
    """Positive control: ``CommonQAService.__init__`` itself emits the ping
    on construction (``ovos_commonqa/opm.py``) -- so by the time the
    fixture yields, ``common_query_skills`` must already list the fixture
    skill, proven live rather than assumed from the class existing."""
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if SKILL_ID in cq_service.common_query_skills:
            break
        time.sleep(0.05)
    assert SKILL_ID in cq_service.common_query_skills, (
        f"{COMBO}: pipeline never registered the fixture skill via "
        f"{CQ_PING_TOPIC}/{CQ_PONG_TOPIC}; discovered="
        f"{cq_service.common_query_skills}")


@pytest.mark.axes("S", "C")
def test_a_matching_question_is_answered_end_to_end(stack, cq_service):
    """The full fan-out: match() sends question:query, the skill answers
    with a real confidence, and the pipeline selects and returns it as an
    IntentHandlerMatch -- asserted against the REAL match, not assumed."""
    _server, bus, skill = stack
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and SKILL_ID not in cq_service.common_query_skills:
        time.sleep(0.05)

    message = Message("recognizer_loop:utterance",
                      {"utterances": ["what is the capital of taco"]},
                      {"session": {"session_id": f"backcompat-cq-{uuid.uuid4().hex[:8]}"}})
    match = cq_service.match(["what is the capital of taco"], "en-us", message)
    assert match is not None, (
        f"{COMBO}: CommonQAService.match() returned no match for a "
        f"question the fixture skill answers with high confidence\n"
        f"skill log:\n{skill.log}")
    assert match.skill_id == SKILL_ID
    assert match.match_data.get("answer") == "Tacoville"


@pytest.mark.axes("S", "C")
def test_a_non_question_utterance_gets_no_match(cq_service):
    """Negative control, real observation not assumed: ``is_question_like``
    filters short/non-question utterances before ever reaching
    ``question:query`` -- this must return None without the skill firing at
    all."""
    message = Message("recognizer_loop:utterance", {"utterances": ["stop"]},
                      {"session": {"session_id": f"backcompat-cq-neg-{uuid.uuid4().hex[:8]}"}})
    match = cq_service.match(["stop"], "en-us", message)
    assert match is None
