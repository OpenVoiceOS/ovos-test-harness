"""The legacy/spec topic pairs the TESTING channel promises to serve, and who
proves each one.

``ovos_spec_tools.messages.MIGRATION_MAP`` is the ecosystem's only list of
events that exist under two names at once. The TESTING channel's defining
property is that both names keep working for the whole migration window, so
the map is also the list of things this harness owes a test.

Two levels of proof are worth keeping apart. The **bus level** is generic:
whichever name a peer emits on, a subscriber on the other name receives the
event once, and no more than once. That holds for every pair without any
service running, and ``test_migration_pairs.py`` drives all of them.

The **component level** is not generic. "Emitting the legacy topic produces
the modern effect" only means something when the component that owns the
effect is alive on the bus — playback for the audio topics, the listener for
the record signals, the intent service for registration. This module records,
per pair, either the harness module that drives the pair against its real
component or the reason no cell does yet, naming the service such a cell would
need. ``test_migration_coverage.py`` fails when a pair has neither, so a topic
added to the map without harness coverage goes red instead of disappearing.
"""
from ovos_spec_tools.messages import MIGRATION_MAP

#: Pairs driven against the real component, on BOTH names, by the module named
#: here. The meta-test requires the module to exist and to carry both topic
#: literals, so deleting one half of a pair's coverage is loud.
COMPONENT_CELLS = {
    "recognizer_loop:utterance": "test/migration/test_pipeline_dual_style.py",
    "speak": "test/backcompat/audio_process.py",
    "recognizer_loop:audio_output_start": "test/backcompat/audio_process.py",
    "recognizer_loop:audio_output_end": "test/backcompat/audio_process.py",
    "mycroft.stop": "test/conformance/test_stop1_conformance.py",
    "complete_intent_failure": "test/skills_fleet/test_fleet_routing.py",
}

#: Pairs with no component-level cell, and the service one would need. These
#: become skipped cells rather than silence: a reader counting the suite sees
#: the gap, and the reason says what to install to close it.
SERVICE_SKIPS = {
    "mycroft.mic.listen":
        "needs ovos-audio (PlaybackService) to answer a listen request",
    "speak:b64_audio":
        "needs ovos-audio (PlaybackService) to render base64 speech",
    "speak:b64_audio.response":
        "needs ovos-audio (PlaybackService) to answer a base64 speak request",
    "mycroft.audio.queue":
        "needs ovos-audio (PlaybackService) to queue a uri",
    "mycroft.audio.play_sound":
        "needs ovos-audio (PlaybackService) to play a sound file",
    "mycroft.audio.speak.status":
        "needs ovos-audio (PlaybackService) to answer the speaking query",
    "mycroft.audio.speech.stop":
        "needs ovos-audio (PlaybackService) to abort playback",
    "recognizer_loop:record_begin":
        "needs ovos-dinkum-listener to open a recording",
    "recognizer_loop:record_end":
        "needs ovos-dinkum-listener to close a recording",
    "recognizer_loop:sleep":
        "needs ovos-dinkum-listener to enter sleep mode",
    "mycroft.awoken":
        "needs ovos-dinkum-listener to leave sleep mode",
    "skill.stop.pong":
        "needs a skill container (ovos-workshop) to answer the stop ping",
    "detach_intent":
        "needs ovos-core's intent service to deregister a live intent",
    "detach_skill":
        "needs ovos-core's intent service to deregister a live skill",
    "mycroft.skill.enable_intent":
        "needs ovos-core's intent service to re-enable a disabled intent",
    "mycroft.skill.disable_intent":
        "needs ovos-core's intent service to disable a live intent",
}


def pair_ids():
    """``legacy -> spec`` ids, in map order, for parametrized cell names."""
    return [f"{legacy} -> {spec.value}" for legacy, spec in MIGRATION_MAP.items()]


def pairs():
    """``(legacy topic, spec topic)`` for every migrating event."""
    return [(legacy, spec.value) for legacy, spec in MIGRATION_MAP.items()]
