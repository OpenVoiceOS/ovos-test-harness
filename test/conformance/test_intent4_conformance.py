"""OVOS-INTENT-4 conformance suite.

Encodes the normative *Conformance* clauses (§11) and the registration bus
surface (§4) of OVOS-INTENT-4 (``ovos/org/architecture/ovos-intent-4.md``) as
ovoscope end-to-end assertions against the ovos-core orchestrator.

INTENT-4 defines a fixed set of registration topics under ``ovos.intent.*`` /
``ovos.entity.*`` and an orchestrator-served introspection manifest
(``ovos.intent.list`` / ``ovos.intent.describe``). This suite asserts the spec
topics directly. The bus-namespace bridge in the harness maps most of the spec
topics onto the legacy in-process mechanism, so those clauses already pass;
the keyword-registration topic has no legacy counterpart and is the one
pending clause. The xfail discipline is described in ``_conformance.py``.

Every test class derives its own skill_id and sample phrasing from its class
name (:class:`_IsolatedRegistrations`), because all classes share one
minicroft and the orchestrator's registration state is process-global: a
shared skill_id would make each class inherit the previous one's state.

Coverage map (clause -> status against current ovos-core):
- §2   registrations are fire-and-forget (no ack / no .response) .. green
- §5   ``ovos.intent.register.keyword`` makes an intent matchable .. xfail (legacy 'padatious:register_intent')
- §6   ``ovos.intent.register.template`` makes an intent matchable  green
- §7   ``ovos.entity.register`` value-set hint ................... green
- §8.2 ``ovos.intent.deregister`` removes an intent .............. green
- §8.3 ``ovos.entity.deregister`` removes an entity .............. green
- §8.4 ``ovos.skill.deregister`` removes a whole skill ........... green
- §8.5 ``ovos.intent.disable`` suppresses an intent .............. green
- §8.5 ``ovos.intent.enable`` re-arms a disabled intent .......... green
- §10.1 ``ovos.intent.list`` introspection responds .............. green
- §10.2 ``ovos.intent.describe`` introspection responds .......... green
- §2/§5.3/§6.2 a malformed registration stays fire-and-forget .... green
- §5.3/§6.2 the orchestrator survives a malformed registration ... green
- §8   deregister of a never-registered skill is a no-op ......... green

The §5.3 companion clause — "MUST log the rejection at WARN with
``skill_id``, the offending value, and the rule violated" — is a
producer/consumer *logging* obligation with no bus emission, so it is
not bus-observable through this harness and is not asserted here (a
malformed registration produces no ``.error`` event by §2). It is
tracked in ``docs/known-gaps.md``.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from ovoscope import (
    get_minicroft,
    register_padatious_entity,
    register_padatious_intent,
)

from ._conformance import (PADACIOSO_HIGH, assert_absent, capture, types,
                           utterance)

ENTITY_NAME = "intent4.skill:color"
ENTITY_SAMPLES = ["red", "green", "blue"]

_MC = None

# Identity used only by the §10 introspection describe query, which asks about
# an intent rather than registering one. Every registering class derives its
# own identity in :class:`_IsolatedRegistrations`.
TEMPLATE_SKILL, TEMPLATE_NAME = "intent4.skill", "lights_on"


def setUpModule():
    global _MC
    LOG.set_level("ERROR")
    _MC = get_minicroft([])
    from ._conformance import wait_ready
    wait_ready(_MC, settle=1.0)


def tearDownModule():
    if _MC is not None:
        _MC.stop()


def _register_template(topic: str, intent: str, samples):
    """Emit a §6 template-registration payload on the given topic."""
    skill_id, intent_name = intent.split(":")
    _MC.bus.emit(Message(topic, {
        "skill_id": skill_id,
        "intent_name": intent_name,
        "lang": "en-US",
        "samples": samples,
    }, {"skill_id": skill_id}))
    time.sleep(1.5)


class _IsolatedRegistrations(TestCase):
    """Base class that gives every test class its own registration identity.

    All classes share one minicroft — booting one per class costs minutes —
    and the orchestrator's registration state is process-global and additive.
    Sharing one ``skill_id`` and one sample set therefore makes each class
    inherit whatever the previous class registered, so results depend on
    definition order. Each class instead derives a unique skill_id, intent
    name and sample phrasing from its own class name, so no class can see
    another's state and the classes can run in any order.
    """

    #: "on" or "off" — the verb the class's sample phrases use
    VERB = "on"

    def setUp(self):
        tag = "".join(c for c in type(self).__name__.lower() if c.isalnum())
        self.tag = tag
        self.skill_id = f"intent4_{tag}.skill"
        self.intent_name = f"lights_{self.VERB}"
        self.intent = f"{self.skill_id}:{self.intent_name}"
        self.entity_name = f"{self.skill_id}:color"
        self.utterance = f"turn {self.VERB} the {tag} lights"
        self.samples = [
            self.utterance,
            f"switch {self.VERB} the {tag} lights",
            f"{tag} lights {self.VERB} please",
        ]

    def register_working(self):
        """Register the class's intent through the mechanism ovos-core already
        supports, so a removal clause has something real to remove."""
        register_padatious_intent(_MC.bus, self.intent, self.samples)
        time.sleep(1.5)

    def emit(self, topic: str, data: dict):
        _MC.bus.emit(Message(topic, {"skill_id": self.skill_id, **data},
                             {"skill_id": self.skill_id}))
        time.sleep(1.5)

    def say(self, session_suffix: str, timeout: float = 3.0):
        return capture(_MC, utterance(self.utterance,
                                      f"i4-{self.tag}-{session_suffix}",
                                      [PADACIOSO_HIGH]), timeout)


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Registrations are fire-and-forget
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2FireAndForget(_IsolatedRegistrations):
    """§2: registration is broadcast and fire-and-forget — there is no
    ``.response`` reply, no acknowledgement, and no error event."""

    def test_no_ack_for_registration(self):
        """Emitting a registration produces no ``.response`` / ack on the bus (§2)."""
        recs = capture(
            _MC,
            Message("ovos.intent.register.template", {
                "skill_id": self.skill_id,
                "intent_name": self.intent_name,
                "lang": "en-US",
                "samples": self.samples,
            }, {"skill_id": self.skill_id}),
            2.0,
        )
        acks = [t for t in types(recs)
                if t.endswith(".response") or t == "ovos.intent.register.template.response"]
        self.assertEqual(acks, [], f"unexpected acknowledgement(s): {acks}")


# ─────────────────────────────────────────────────────────────────────────────
# §6 / §8 — Registration and deregistration bus contract
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6TemplateRegistration(_IsolatedRegistrations):
    """§6: a template intent registered on ``ovos.intent.register.template``
    becomes matchable; a match dispatches ``<skill_id>:<intent_name>``."""

    def test_spec_topic_registration_is_matchable(self):
        """Registering via the spec topic makes the intent matchable (§6)."""
        _register_template("ovos.intent.register.template", self.intent,
                           self.samples)
        recs = self.say("tmpl")
        self.assertIn(self.intent, types(recs))


class TestSec82Deregister(_IsolatedRegistrations):
    """§8.2: ``ovos.intent.deregister`` removes one intent so it no longer
    matches."""

    def test_spec_deregister_removes_intent(self):
        """After a spec-topic deregister, the intent must no longer match (§8.2)."""
        # register via the working mechanism so there is something to remove
        self.register_working()
        self.emit("ovos.intent.deregister",
                  {"intent_name": self.intent_name, "lang": "en-US"})
        recs = self.say("dereg")
        assert_absent(recs, self.intent)


class TestSec85Disable(_IsolatedRegistrations):
    """§8.5: ``ovos.intent.disable`` temporarily suppresses an intent without
    removing its definition."""

    def test_spec_disable_suppresses_intent(self):
        """A disabled intent is excluded from match candidacy (§8.5)."""
        self.register_working()
        self.emit("ovos.intent.disable",
                  {"intent_name": self.intent_name, "lang": "en-US"})
        recs = self.say("disable")
        assert_absent(recs, self.intent)


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Keyword-intent registration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5KeywordRegistration(_IsolatedRegistrations):
    """§5: a keyword intent registered on ``ovos.intent.register.keyword``
    becomes matchable; a match dispatches ``<skill_id>:<intent_name>``."""

    VERB = "off"

    @pytest.mark.xfail(strict=True,
                       reason="ovos-core consumes keyword registration via the legacy "
                              "'padatious:register_intent'/'register_intent'; INTENT-4 "
                              "§5 defines 'ovos.intent.register.keyword'")
    def test_spec_keyword_registration_is_matchable(self):
        """Registering via the spec keyword topic makes the intent matchable (§5)."""
        self.emit("ovos.intent.register.keyword",
                  {"intent_name": self.intent_name, "lang": "en-US",
                   "samples": self.samples})
        recs = self.say("kw")
        self.assertIn(self.intent, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §3.2 / §5.3 / §6.2 — Malformed-registration rejection
# ─────────────────────────────────────────────────────────────────────────────

class TestSec53MalformedRejection(_IsolatedRegistrations):
    """§5.3 / §6.2 / §3.2: a consuming plugin MUST NOT index a malformed
    registration, and (§2) a registration is fire-and-forget — even a
    malformed one draws no ``.response`` ack and no ``.error`` event.

    Two malformed payloads are exercised: a ``ovos.intent.register.template``
    with no ``samples`` (§6.2: "``samples`` is missing or empty") and a
    ``ovos.entity.register`` with an empty value-set (§7: rejected when
    ``samples`` is missing or empty). Neither may become matchable, and
    neither may crash or corrupt the orchestrator — a subsequent well-formed
    registration on the same skill must still match (the observable proxy for
    "not indexed + no crash", since the WARN-log rule is not bus-observable).
    """

    VERB = "off"

    def test_malformed_registration_is_fire_and_forget(self):
        """A malformed template registration draws no ack and no error (§2, §6.2)."""
        recs = capture(
            _MC,
            Message("ovos.intent.register.template", {
                "skill_id": self.skill_id,
                "intent_name": self.intent_name,
                "lang": "en-US",
                # §6.2 malformed: no `samples`
            }, {"skill_id": self.skill_id}),
            2.0,
            eof_types=None,
        )
        acks = [t for t in types(recs)
                if t.endswith(".response") or t.endswith(".error")]
        self.assertEqual(acks, [], f"malformed registration drew a reply: {acks}")

    def test_orchestrator_survives_malformed_registration(self):
        """After malformed template + entity registrations, a subsequent
        well-formed registration on the same skill still matches — the
        malformed payloads were not indexed and did not corrupt state
        (§5.3 / §6.2 / §3.2)."""
        # malformed template: no samples
        self.emit("ovos.intent.register.template",
                  {"intent_name": "bogus_intent", "lang": "en-US"})
        # malformed entity: empty value-set
        self.emit("ovos.entity.register",
                  {"name": f"{self.skill_id}:empty", "lang": "en-US",
                   "samples": []})
        # Observable proxy for "not indexed + no crash": a subsequent
        # well-formed registration on the same skill still matches. (A direct
        # "bogus_intent is not matchable" assertion is unprovable here — a
        # no-samples registration has no phrase that could trigger it — and a
        # bare padatious intent has no completing handler, so the turn emits no
        # terminal event to make a negative assertion non-vacuous.)
        self.register_working()
        recs = self.say("survives")
        self.assertIn(self.intent, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §8 — Deregistering a never-registered skill is a no-op
# ─────────────────────────────────────────────────────────────────────────────

class TestSec8DeregisterUnregistered(_IsolatedRegistrations):
    """§8: "Deregistering an intent, entity, or skill that is not currently
    registered is a no-op" — fire-and-forget and naturally idempotent. It
    draws no ack/error and does not disturb a later well-formed registration."""

    VERB = "off"

    def test_deregister_never_registered_skill_is_noop(self):
        """A ``ovos.skill.deregister`` for a skill never registered is a
        no-op: no ack/error, and a subsequent registration still matches (§8)."""
        recs = capture(
            _MC,
            Message("ovos.skill.deregister", {},
                    {"skill_id": self.skill_id}),
            2.0,
            eof_types=None,
        )
        acks = [t for t in types(recs)
                if t.endswith(".response") or t.endswith(".error")]
        self.assertEqual(acks, [], f"no-op deregister drew a reply: {acks}")
        # positive control: the orchestrator is unharmed
        self.register_working()
        matched = self.say("noop")
        self.assertIn(self.intent, types(matched))


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Entity (value-set) registration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7EntityRegistration(TestCase):
    """§7: ``ovos.entity.register`` registers a value-set hint that the matcher
    can resolve as a named slot. Registration is fire-and-forget (§2)."""

    def test_spec_entity_registration_no_ack(self):
        """Emitting an entity registration on the spec topic produces no ack and is
        accepted by an INTENT-4 consumer (§7, §2)."""
        recs = capture(_MC, Message("ovos.entity.register", {
            "skill_id": ENTITY_NAME.split(":")[0],
            "name": ENTITY_NAME,
            "lang": "en-US",
            "samples": ENTITY_SAMPLES,
        }, {"skill_id": ENTITY_NAME.split(":")[0]}), 2.0)
        acks = [t for t in types(recs) if t.endswith(".response")]
        self.assertEqual(acks, [], f"unexpected acknowledgement(s): {acks}")
        # an INTENT-4 consumer must not reject a well-formed entity payload
        assert_absent(recs, "ovos.entity.register.error",
                      positive_control="ovos.entity.register")


# ─────────────────────────────────────────────────────────────────────────────
# §8.3 / §8.4 — Entity and whole-skill deregistration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec83EntityDeregister(TestCase):
    """§8.3: ``ovos.entity.deregister`` removes one entity value-set hint."""

    def test_spec_entity_deregister_no_error(self):
        """A spec-topic entity deregister is consumed without an error event (§8.3)."""
        register_padatious_entity(_MC.bus, ENTITY_NAME, ENTITY_SAMPLES)
        time.sleep(1.0)
        recs = capture(_MC, Message("ovos.entity.deregister", {
            "skill_id": ENTITY_NAME.split(":")[0],
            "name": ENTITY_NAME, "lang": "en-US",
        }, {"skill_id": ENTITY_NAME.split(":")[0]}), 2.0)
        assert_absent(recs, "ovos.entity.deregister.error",
                      positive_control="ovos.entity.deregister")


class TestSec84SkillDeregister(_IsolatedRegistrations):
    """§8.4: ``ovos.skill.deregister`` removes every intent and entity registered
    under one ``skill_id`` in a single broadcast."""

    VERB = "off"

    def test_spec_skill_deregister_removes_all_intents(self):
        """After a spec-topic skill deregister, none of the skill's intents match (§8.4)."""
        self.register_working()
        self.emit("ovos.skill.deregister", {})
        recs = self.say("skilldereg")
        assert_absent(recs, self.intent)


# ─────────────────────────────────────────────────────────────────────────────
# §8.5 — Enable re-arms a disabled intent
# ─────────────────────────────────────────────────────────────────────────────

class TestSec85Enable(_IsolatedRegistrations):
    """§8.5: ``ovos.intent.enable`` re-arms an intent previously suppressed by
    ``ovos.intent.disable``, restoring its match candidacy."""

    VERB = "off"

    def test_spec_enable_rearms_intent(self):
        """A disabled-then-enabled intent matches again (§8.5)."""
        self.register_working()
        self.emit("ovos.intent.disable",
                  {"intent_name": self.intent_name, "lang": "en-US"})
        self.emit("ovos.intent.enable",
                  {"intent_name": self.intent_name, "lang": "en-US"})
        recs = self.say("enable")
        self.assertIn(self.intent, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §10 — Orchestrator-owned introspection manifest
# ─────────────────────────────────────────────────────────────────────────────

class TestSec10Introspection(TestCase):
    """§10 / §11: the orchestrator MUST serve ``ovos.intent.list`` and
    ``ovos.intent.describe`` against its passive registration manifest."""

    def test_intent_list_responds(self):
        """A query on ``ovos.intent.list`` yields an ``ovos.intent.list.response`` (§10.1)."""
        recs = capture(_MC, Message("ovos.intent.list", {}, {"source": "A"}), 2.0)
        self.assertIn("ovos.intent.list.response", types(recs))

    def test_intent_describe_responds(self):
        """A query on ``ovos.intent.describe`` yields an
        ``ovos.intent.describe.response`` (§10.2)."""
        recs = capture(_MC, Message("ovos.intent.describe", {
            "skill_id": TEMPLATE_SKILL, "intent_name": TEMPLATE_NAME, "lang": "en-US",
        }, {"source": "A"}), 2.0)
        self.assertIn("ovos.intent.describe.response", types(recs))
