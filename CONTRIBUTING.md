# Contributing

`ovos-test-harness` proves that a combination of cross-repo branches conforms
to the [`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specs. Start at [docs/testing-combos.md](docs/testing-combos.md) — it is the
entry path for the workflow this repo exists to support: picking a branch
combination, editing `requirements.txt`, and reading the conformance verdict
from a PR.

Before writing a new test, read
[docs/writing-conformance-tests.md](docs/writing-conformance-tests.md).

## Setup

```bash
sudo apt-get install -y swig libfann-dev   # padatious needs these to build
pip install -r requirements.txt
pytest test/ -v --tb=short
```

## The "always glob, never name" rule

CI must always discover test files by glob (`pytest test/`,
`test/backcompat/**`, `test_*_conformance.py`, and so on), never by naming an
individual file. A hardcoded filename in a workflow silently stops running
the moment that file is renamed or split, and the suite reports green while
covering less than it did before. If you add a new conformance module, a new
backcompat cell, or a new channel-gaps case, it must be picked up by the
existing globs with no workflow edit required. If it isn't, fix the glob —
do not add the filename.

## Branches

- `dev` — active development, open PRs here.
- Feature branches merge into `dev` as draft PRs; a maintainer reviews and
  merges.

## Commit style

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new functionality
- `fix:` bug fixes
- `chore:` maintenance (deps, CI, packaging)
- `docs:` documentation only

## Pull requests

- Target the `dev` branch.
- Keep `requirements.txt` diffs reviewable: one ref change per line, with a
  comment explaining why (see [docs/how-it-works.md](docs/how-it-works.md)).
- Do not edit `docs/coverage.md` or `docs/known-gaps.md` by hand outside a
  conformance-suite change — they track what the test suite actually proves.
- Validate any workflow YAML you touch:
  `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/<file>.yml'))"`.

## See also

- [docs/ci.md](docs/ci.md) — what each CI job runs and why.
- [docs/how-it-works.md](docs/how-it-works.md) — the `requirements.txt`-driven
  install model.
