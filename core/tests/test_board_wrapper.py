"""core/bin/omni-board runs this checkout's board, whatever the machine's env or working directory.

Two ways another copy of core used to win, both seen on a live instance:
- the instance's env file (loaded by omni-svc) sets PYTHONPATH, pointing at the instance's core;
- `python -m` puts the working directory first on sys.path, so running the wrapper from inside
  another checkout's core/ imported that checkout's omni_core.
Either way `omni board` didn't exist, or worse, ran another version.
"""
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def _decoy(where: Path) -> Path:
    pkg = where / "omni_core"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "cli.py").write_text("import sys\nprint('DECOY')\nsys.exit(3)\n")
    return where


def _run(tmp_path, *, env_line='UNRELATED="1"', cwd=None):
    env_dir = tmp_path / "env"
    env_dir.mkdir(exist_ok=True)
    (env_dir / "machine.env").write_text(env_line + "\n")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "OMNI_ENV_DIR": str(env_dir),
           "OMNI_SVC": str(CORE / "bin" / "omni-svc"), "OMNI_PYTHON": sys.executable, "OMNI_AGENT": "test"}
    return subprocess.run([str(CORE / "bin" / "omni-board"), "list"], env=env, capture_output=True, text=True,
                          cwd=cwd or tmp_path)


def _ran_this_core(result):
    # With no board configured, this checkout's board refuses cleanly; a decoy prints DECOY instead.
    return "DECOY" not in result.stdout and result.returncode == 2 and "no board" in result.stderr


def test_an_env_file_pythonpath_does_not_shadow_this_checkouts_core(tmp_path):
    decoy = _decoy(tmp_path / "instance-core")
    assert _ran_this_core(_run(tmp_path, env_line=f'PYTHONPATH="{decoy}"'))


def test_running_from_inside_another_core_does_not_import_it(tmp_path):
    other = _decoy(tmp_path / "other-checkout" / "core")
    assert _ran_this_core(_run(tmp_path, cwd=other))


def test_plain_case_still_runs_this_core(tmp_path):
    assert _ran_this_core(_run(tmp_path))
