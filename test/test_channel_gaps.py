"""The other half of the channel known-gaps guard.

``conftest.py`` skips collecting the suites a channel cannot import and strict-
xfails the node ids the channel fails. Both are permissive by nature, so on
their own they would let a stale gaps file hide real progress or real breakage.

These tests close that hole:

* every suite listed under ``[modules]`` must STILL fail to import — when the
  channel catches up, the line has to go, and this test says so;
* every suite NOT listed must import — this is the channel-mode replacement for
  ``OVOS_CONFORMANCE_EXPECT_FULL``, which cannot be used here because a channel
  install is partial by construction (no channel ships ovos-media, for one).

They run only in channel mode. A dev-stack run skips them.
"""
import importlib
import os

import pytest

from test.channel_compat.gaps import read_gaps

CHANNEL = os.environ.get("OVOS_CHANNEL") or None

pytestmark = pytest.mark.skipif(
    CHANNEL is None, reason="not a channel run (OVOS_CHANNEL is unset)")

CONFORMANCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "conformance")
_MODULE_GAPS = read_gaps(CHANNEL)[0] if CHANNEL else set()


def _module_name(rel_path):
    return rel_path[:-len(".py")].replace("/", ".")


def _all_suites():
    return sorted(f"test/conformance/{name}"
                  for name in os.listdir(CONFORMANCE_DIR)
                  if name.startswith("test_") and name.endswith(".py"))


@pytest.mark.parametrize("rel_path", sorted(_MODULE_GAPS))
def test_listed_module_still_fails_to_import(rel_path):
    """A closed module-level gap must be deleted from the gaps file."""
    with pytest.raises(ImportError):
        importlib.import_module(_module_name(rel_path))


@pytest.mark.parametrize("rel_path",
                         [p for p in _all_suites() if p not in _MODULE_GAPS])
def test_unlisted_module_imports(rel_path):
    """Every suite the gaps file does not excuse must import on this channel."""
    importlib.import_module(_module_name(rel_path))
