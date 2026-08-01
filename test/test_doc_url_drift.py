"""Meta-test: doc code-fence git URLs must not drift from requirements.txt.

DOR-003 (README/docs pointed `ovoscope` at `TigreGotico/ovoscope` while
`requirements.txt` installs it from `OpenVoiceOS/ovoscope`) and DOR-004 (doc
example blocks asserting a stale ref as "the live file") are the same class
of bug: a `git+https://github.com/<owner>/<repo>@<ref>` line inside a
fenced code block in README.md or docs/*.md, silently going stale next to
the real `requirements.txt`.

This test parses every fenced code block (``` ``` ``` ``` or ```` ```diff ````)
in README.md and docs/*.md, extracts each `git+https://github.com/<owner>/
<repo>` reference it contains, and requires one of:

  * `<owner>/<repo>` matches a `git+https://github.com/<owner>/<repo>` line
    in `requirements.txt` (the ref itself may differ — combo examples
    legitimately show a branch under test, not `@dev`), or
  * the block is explicitly marked illustrative: the word "illustrative"
    appears in the text between the previous heading and the block.

A doc block that names a repo requirements.txt does not install, under an
org requirements.txt does not use, with no "illustrative" marker, is either
wrong today or will go stale unnoticed — exactly the DOR-003/004 failure
mode. Fixing that requires either updating requirements.txt, fixing the
doc's org/repo, or marking the block illustrative.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).parent.parent

FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
HEADING = re.compile(r"^#{1,6}\s.*$", re.MULTILINE)
GIT_URL = re.compile(r"git\+https://github\.com/([\w.-]+)/([\w.-]+?)(?:@|\.git|\s|$)")


def _requirements_repos():
    """{(owner, repo)} for every git+https github line in requirements.txt."""
    text = (ROOT / "requirements.txt").read_text()
    return {(m.group(1), m.group(2)) for m in GIT_URL.finditer(text)}


def _doc_files():
    files = [ROOT / "README.md"]
    files += sorted((ROOT / "docs").glob("*.md"))
    return files


def _blocks_with_context(text):
    """Yield (preceding_text_since_last_heading, block_body) pairs."""
    headings = [m.start() for m in HEADING.finditer(text)]
    for m in FENCE.finditer(text):
        block_start = m.start()
        # text since the last heading before this block (or start of file)
        section_start = 0
        for h in headings:
            if h <= block_start:
                section_start = h
            else:
                break
        yield text[section_start:block_start], m.group(1)


@pytest.mark.parametrize("path", _doc_files(), ids=lambda p: p.name)
def test_doc_git_urls_match_requirements_or_are_illustrative(path):
    requirements_repos = _requirements_repos()
    text = path.read_text()
    offenders = []
    for context, body in _blocks_with_context(text):
        is_illustrative = "illustrative" in context.lower()
        for m in GIT_URL.finditer(body):
            owner, repo = m.group(1), m.group(2)
            if (owner, repo) in requirements_repos:
                continue
            if is_illustrative:
                continue
            offenders.append(f"{owner}/{repo}")
    assert not offenders, (
        f"{path.name}: code-fence reference(s) to {sorted(set(offenders))} "
        f"match no git+https line in requirements.txt and the containing "
        f"block is not marked illustrative. Either fix requirements.txt, "
        f"fix the doc's org/repo, or mark the block as illustrative."
    )
