# Instruments

An instrument is code a gate installs to make a measurement possible. It is
not part of the stack under test, it never goes in a freeze file, and no
verdict is recorded about it.

## gate_probe_provider

A MediaProvider that records the `Signals` the OCP pipeline hands it and
returns no releases.

### The problem it solves

`_is_bare_media_request` is called only from `_provider_signals`.
`_provider_signals` is called only from the in-process MediaProvider
dispatch, and that dispatch returns early when no provider is loaded. With no
provider installed the branch is dead code.

This is not a theory. The gate on `ovos-ocp-pipeline-plugin#175` first drove
eight utterances across two trees, in two languages. Every one agreed, and
the pipeline's own bare-request log line had zero hits on both sides. The
drive looked like a clean negative result. It was measuring a branch that
never ran.

A live drive that installs no provider cannot tell two trees apart on that
branch, whatever utterances it sends. Install the probe first.

### Use

```python
from test.instruments import probe

probe.install(venv_python, source_root=REPO_ROOT)
assert probe.is_discovered(venv_python)

log = tmp_path / "dev.jsonl"
run_the_drive(env={**os.environ, "GATE_PROBE_LOG": str(log)})
assert probe.titles(probe.read_log(log)) == ["music music"]
```

`install` names the interpreter explicitly and uses `uv`. It returns the
command it ran, for the evidence file's `CMD:` line.

`is_discovered` asks OPM, not the filesystem. A package that installs but
whose entry point does not register is the failure this instrument exists to
rule out, and only the loader can see it. Call it once per venv and record
the answer: it is the control that says the measurement below is real.

A missing log file reads as no searches. That is a measurement, not an
error, and it is what a dead dispatch branch looks like.

### Why it is a separate installable package

OPM finds providers by entry point. A module on `sys.path` is never
discovered, so the probe has to be installed into the venv under test.

### What keeps it honest

`test/test_gate_probe_provider.py`. The cells are offline and install
nothing. They hold the entry point to a class that exists, hold the provider
name to the same string in both files, and hold `search` to a literal empty
return, so the probe can never promote a release or move a confidence.
