"""The architecture spec corpus, pinned at a recorded commit.

The conformance suites cite spec sections by number in their docstrings, and
`docs/coverage.md` / `docs/known-gaps.md` claim a status per clause. Nothing
checks those claims against the specs themselves, so a clause can be written,
ratified and shipped without ever growing a cell or an admission that it has
none.

This module gives the meta-tests the corpus to check against. It fetches
`OpenVoiceOS/architecture` at the commit recorded in `architecture.sha` into a
user cache directory and hands back the spec documents. The pin is deliberate:
the corpus moves when someone bumps that file, so a spec change lands together
with the coverage rows it forces, rather than turning the meta-tests red on an
unrelated pull request.
"""
import os
import pathlib
import re
import subprocess

REPO = "https://github.com/OpenVoiceOS/architecture"
HERE = pathlib.Path(__file__).parent
SHA = (HERE / "architecture.sha").read_text().strip()

# `| OVOS-MSG-1 | [Bus Message](msg-1.md) | 1 | Draft |`
_README_ROW = re.compile(
    r"^\|\s*(OVOS-[A-Z0-9-]+)\s*\|\s*\[[^\]]+\]\(([a-z0-9-]+\.md)\)", re.MULTILINE)
_HEADING = re.compile(r"^(#{2,3})\s+(\d+(?:\.\d+)*)\.?\s", re.MULTILINE)


def corpus_dir():
    """The checkout of the pinned architecture commit, fetching it if needed."""
    cache = pathlib.Path(
        os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache"))
    dest = cache / "ovos-test-harness" / "architecture" / SHA
    if not (dest / "README.md").is_file():
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        subprocess.run(["git", "fetch", "-q", "--depth", "1", REPO, SHA],
                       cwd=dest, check=True)
        subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"],
                       cwd=dest, check=True)
    return dest


def specs():
    """`{spec_id: document path}` for every spec the corpus README indexes."""
    root = corpus_dir()
    return {spec_id: root / name
            for spec_id, name in _README_ROW.findall(
                (root / "README.md").read_text())}


def sections(path):
    """The numbered `##` / `###` section numbers of one spec document."""
    return [num for _, num in _HEADING.findall(path.read_text())]
