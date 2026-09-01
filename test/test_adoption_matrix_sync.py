"""Meta-test: `docs/adoption.md` must not drift from `docs/coverage.md` or
from reality.

`docs/adoption.md` claims to be a per-repo spec adoption matrix, one section
per spec `docs/coverage.md` tracks, with every evidence link commit-pinned
and pointing at a line that actually contains the topic string the row
claims. Being hand-maintained Markdown, all of those claims can quietly go
stale: a new spec section lands in `coverage.md` with no matching adoption
section, an evidence link gets edited into a branch URL, or a link's line
number drifts away from the string it was originally pinned to (a defect
that shipped in the first version of this page and was only caught by a
manual audit — this test exists so the next drift is caught automatically).

This mirrors `test_docs_tracker_sync.py`'s approach: parse both documents'
`## OVOS-<ID>` headings and diff the spec-id sets, then regex-validate every
GitHub blob permalink in `adoption.md`, and for every permalink whose repo
is checked out locally, `git show <sha>:<path>` at that exact commit and
assert the row's claimed topic string sits on the referenced line.
"""
import pathlib
import re

import pytest

DOCS = pathlib.Path(__file__).parent.parent / "docs"
WORKSPACE = pathlib.Path.home() / "AgentWorkspaces"

SPEC_ID = re.compile(r"OVOS-[A-Z]+(?:-[A-Z]+)*-\d+")
HEADING = re.compile(r"^##\s+.*$", re.MULTILINE)

# Repo slug (as it appears in the GitHub URL) -> checkout path relative to
# ~/AgentWorkspaces, resolved once via `where.py --local <repo>` and cached
# here rather than shelling out to it on every test run.
REPO_PATHS = {
    "ovos-core": "ovos/core/ovos-core",
    "ovos-audio": "ovos/core/ovos-audio",
    "ovos-gui": "ovos/gui/ovos-gui",
    "pyhtmx-gui-client": "ovos/gui/pyhtmx-gui-client",
    "ovoscope": "ovos/tools/ovoscope",
    "ovos-pydantic-models": "ovos/core/ovos-pydantic-models",
    "ovos-workshop": "ovos/core/ovos-workshop",
    "ovos-markov-pipeline-plugin": "ovos/ovos-markov-pipeline-plugin",
    "padacioso": "ovos/padacioso",
    "ovos-control-panel": "ovos/ovos-webui",  # historical rename; local dir kept the old name
    "ovos-bus-client": "ovos/core/ovos-bus-client",
    "ovos-plugin-manager": "ovos/core/ovos-plugin-manager",
    "ovos-gui-api-client": "ovos/gui/ovos-gui-api-client",
    "ovos-gui-plugin-ag-ui": "ovos/gui/ovos-gui-plugin-ag-ui",
    "HiveMind-core": "hivemind/core/hivemind-core",
    "hivescope": "hivemind/core/hivescope",
    "ovos-ui-enclosure-protocol": "ovos/ovos-ui-enclosure-protocol",
    "ovos-media": "ovos/core/ovos-media",
    "ovos-skill-alerts": "ovos/skills/ovos-skill-alerts",
    "ovos-persona": "ovos/plugins/pipeline/ovos-persona",
    "ovos-spec-tools": "ovos/tools/ovos-spec-tools",
}

# GitHub blob URL: org/repo/blob/<ref>/<path>#L<line>. A commit-pinned ref is
# a git SHA; branch names like "dev", "main", "master" must be rejected, so
# this captures any ref chars and validates the ref value separately rather
# than only matching hex (a branch name like "dev" is itself all-hex-looking
# characters for two of its three letters, which silently defeated an
# earlier, stricter-looking version of this regex).
BLOB_URL = re.compile(
    r"\[([^\]]*)\]\(https://github\.com/([\w.-]+)/([\w.-]+)/blob/([\w.-]+)/(\S+?)#L(\d+)\)")
BRANCH_NAMES = {"dev", "main", "master", "HEAD"}


def _headings(doc_name):
    text = (DOCS / doc_name).read_text()
    return HEADING.findall(text)


def _spec_ids_from_headings(headings):
    ids = set()
    for h in headings:
        ids.update(SPEC_ID.findall(h))
    return ids


def test_every_coverage_spec_has_an_adoption_section():
    """Every `## OVOS-<ID>` in coverage.md has a matching section in adoption.md."""
    coverage_ids = _spec_ids_from_headings(_headings("coverage.md"))
    adoption_ids = _spec_ids_from_headings(_headings("adoption.md"))
    missing = coverage_ids - adoption_ids
    assert not missing, (
        f"docs/coverage.md declares {sorted(missing)} but docs/adoption.md "
        f"has no matching '## ...OVOS-<ID>...' section.")


ADOPTION_TEXT = (DOCS / "adoption.md").read_text() if (DOCS / "adoption.md").exists() else ""


def _table_rows():
    """Every Markdown table row in adoption.md that contains at least one
    GitHub blob link, split into cells. Used to recover the row's claimed
    topic (the first backtick-quoted token in the row) alongside its link.
    """
    rows = []
    for line in ADOPTION_TEXT.splitlines():
        if not line.strip().startswith("|") or "github.com" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append((line, cells))
    return rows


def _blob_links_with_context():
    """(link_text, org, repo, ref, path, line, full_row_line) for every link."""
    out = []
    for row_line, cells in _table_rows():
        for m in BLOB_URL.finditer(row_line):
            link_text, org, repo, ref, path, line = m.groups()
            out.append((link_text, org, repo, ref, path, int(line), row_line))
    return out


def _claimed_topic(row_line):
    """The first backtick-quoted token in a table row — the topic/symbol the
    row's evidence link is supposed to substantiate."""
    m = re.search(r"`([^`]+)`", row_line)
    return m.group(1) if m else None


def test_adoption_permalinks_are_commit_pinned():
    """Every GitHub blob link in adoption.md must pin a commit, not a branch."""
    links = _blob_links_with_context()
    assert links, "docs/adoption.md has no GitHub blob permalinks at all."
    for _, org, repo, ref, path, line, row_line in links:
        assert ref not in BRANCH_NAMES, (
            f"https://github.com/{org}/{repo}/blob/{ref}/{path}#L{line} uses "
            f"a branch name ({ref!r}) instead of a pinned commit SHA.")
        assert re.fullmatch(r"[0-9a-fA-F]{7,40}", ref), (
            f"https://github.com/{org}/{repo}/blob/{ref}/{path}#L{line} — "
            f"{ref!r} does not look like a git commit SHA.")


@pytest.mark.parametrize(
    "org,repo",
    sorted({(org, repo) for _, org, repo, _, _, _, _ in _blob_links_with_context()}),
    ids=lambda v: v if isinstance(v, str) else f"{v[0]}/{v[1]}")
def test_named_repo_resolves_to_a_local_checkout(org, repo):
    """Every repo an evidence link points at must be a real, mapped checkout."""
    checkout = REPO_PATHS.get(repo)
    if checkout is None:
        pytest.fail(
            f"docs/adoption.md links into {org}/{repo}, but {repo!r} is not "
            f"in REPO_PATHS. Resolve it with `where.py --local {repo}` and "
            f"add the mapping (or the repo to a documented exceptions list "
            f"if it is genuinely not cloned).")
    path = WORKSPACE / checkout
    if not path.is_dir():
        pytest.skip(f"{checkout} is not checked out in this environment")


_LINK_CASES = _blob_links_with_context()


@pytest.mark.parametrize(
    "link_text,org,repo,ref,path,line,row_line",
    _LINK_CASES,
    ids=[f"{org}/{repo}#L{line}" for _, org, repo, _, _, line, _ in _LINK_CASES])
def test_permalink_line_contains_its_claimed_topic(link_text, org, repo, ref, path, line, row_line):
    """The pinned line must actually contain the topic string the row claims.

    This is the check that would have caught the original page's defect:
    17 of its permalinks pointed at a plausible-looking but wrong line
    (often a docstring or comment a few lines away from the real hit) inside
    the right file at the right commit. `git show <sha>:<path>` reads the
    file exactly as it existed at that commit — no network call, no branch
    drift — and the claimed topic (the first backtick-quoted token in the
    row) must appear on the exact referenced line.
    """
    checkout = REPO_PATHS.get(repo)
    if checkout is None or not (WORKSPACE / checkout).is_dir():
        pytest.skip(f"{repo} is not checked out in this environment")
    repo_dir = WORKSPACE / checkout
    topic = _claimed_topic(row_line)
    assert topic, f"row for {org}/{repo}#L{line} has no backtick-quoted claimed topic to check"
    import subprocess
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=repo_dir,
        capture_output=True, text=True)
    assert result.returncode == 0, (
        f"`git show {ref}:{path}` failed in {checkout} "
        f"(commit not fetched locally, or path renamed): {result.stderr.strip()}")
    lines = result.stdout.split("\n")
    assert 0 < line <= len(lines), (
        f"{org}/{repo}#L{line} — file only has {len(lines)} lines at {ref}.")
    actual = lines[line - 1]
    assert topic in actual, (
        f"{org}/{repo}/blob/{ref}/{path}#L{line} claims `{topic}` but that "
        f"line reads: {actual.strip()!r}")


