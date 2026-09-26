"""A MediaProvider that records the Signals the OCP pipeline hands it.

Why this exists. ``_is_bare_media_request`` is called only from
``_provider_signals``, and ``_provider_signals`` is called only from the
in-process MediaProvider dispatch, which returns early when no provider is
loaded (``ocp_pipeline/opm.py``). With no provider installed that branch is
dead code: a live drive that installs none cannot tell two trees apart on it,
whatever utterances it sends. A gate on ovos-ocp-pipeline-plugin#175 first
measured eight utterances that agreed on dev and on the head, with zero hits
for the pipeline's own bare-request log line, for exactly that reason.

This provider makes the dispatch reachable and nothing else. It returns no
releases, so it cannot change any match, promote a result, or alter a
confidence. It only writes down what it was asked.

Each search appends one JSON object to ``GATE_PROBE_LOG``. Read it back with
``test.instruments.probe.read_log``.
"""
import json
import os
from typing import List, Optional, Set

from ovos_plugin_manager.templates.media_provider import MediaProvider

#: Where each search is recorded, one JSON object per line. The drive sets
#: this per run; a shared default would mix two runs into one file and the
#: reader cannot tell them apart.
LOGFILE_ENV = "GATE_PROBE_LOG"

#: The entry-point name. ``test/test_gate_probe_provider.py`` asserts the
#: pyproject entry point agrees with this string, so a rename cannot leave the
#: instrument silently undiscoverable.
PROVIDER_NAME = "gate-probe-provider"


def logfile() -> str:
    """The path this process records to."""
    return os.environ.get(LOGFILE_ENV, "/tmp/gate-probe-provider.jsonl")


class GateProbeProvider(MediaProvider):
    """Records every search, returns nothing."""

    name = PROVIDER_NAME

    def search(self, signals, lang: str = "en-us", *,
               supported_playback_types: Optional[Set[str]] = None,
               blocked_genres: Optional[Set[str]] = None,
               region: Optional[str] = None,
               session_id: Optional[str] = None) -> List:
        row = {"lang": lang,
               "title": getattr(signals, "title", None),
               "medium": str(getattr(signals, "medium", None)),
               "role": str(getattr(signals, "role", None)),
               "session_id": session_id}
        # Read with getattr and str() on purpose: the point of the probe is to
        # record what arrived, including a shape this instrument does not know
        # about. An AttributeError here would lose the measurement.
        with open(logfile(), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return []
