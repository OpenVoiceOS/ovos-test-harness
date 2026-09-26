"""Install the gate probe provider into a venv, and read back what it saw.

The provider itself is a separate installable package
(``test/instruments/gate_probe_provider``) because OPM discovers providers by
entry point: a module sitting on ``sys.path`` is never found. It has to be
installed into the venv under test, which is also why it cannot live in this
module.

Typical use in a live drive, once per tree::

    log = tmp / "dev.jsonl"
    install(dev_venv_python, source_root=REPO_ROOT)
    run_the_drive(env={**os.environ, "GATE_PROBE_LOG": str(log)})
    assert titles(read_log(log)) == ["music music"]

The probe is an instrument, not a dependency: it is never added to a freeze
file and never installed into a tree a verdict is recorded against for any
other reason.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

#: The instrument package, relative to the repository root.
PACKAGE = Path("test/instruments/gate_probe_provider")

#: The entry-point name OPM registers it under.
PROVIDER_NAME = "gate-probe-provider"

#: The environment variable naming the log file.
LOGFILE_ENV = "GATE_PROBE_LOG"


def install(python: str, source_root: Optional[Path] = None,
            prerelease: bool = True) -> str:
    """Install the probe provider into the venv owning ``python``.

    ``uv``, never ``pip``, and the interpreter is named explicitly rather than
    inherited from an activated venv: a drive runs several venvs in one
    process and an implicit target installs into whichever one happens to be
    active.

    Returns the command that was run, for the evidence file's ``CMD:`` line.
    """
    root = Path(source_root) if source_root else Path(__file__).resolve().parents[2]
    pkg = root / PACKAGE
    if not (pkg / "pyproject.toml").is_file():
        raise FileNotFoundError(f"no probe provider package at {pkg}")
    cmd = ["uv", "pip", "install", "--python", str(python), str(pkg)]
    if prerelease:
        cmd.insert(3, "--prerelease=allow")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    subprocess.run(cmd, check=True, env=env)
    return " ".join(cmd)


def is_discovered(python: str) -> bool:
    """Whether OPM finds the probe in that venv.

    Ask OPM, not the filesystem. An installed package whose entry point did
    not register is the failure this instrument exists to rule out, and only
    the loader can see it.
    """
    code = ("from ovos_plugin_manager.media_provider import "
            "find_media_provider_plugins as f; "
            f"print({PROVIDER_NAME!r} in f())")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    out = subprocess.run([python, "-c", code], capture_output=True, text=True,
                         env=env)
    return out.stdout.strip() == "True"


def read_log(path) -> List[Dict[str, Any]]:
    """Every search the probe recorded, in order.

    A missing file reads as no searches, which is a real measurement: it is
    what a dead dispatch branch looks like. A malformed line is skipped rather
    than raised, so a truncated final write from a killed process does not
    lose the rows before it.
    """
    rows = []
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def titles(rows: List[Dict[str, Any]]) -> List[Optional[str]]:
    """The title each search carried, in order. The usual assertion target."""
    return [r.get("title") for r in rows]
