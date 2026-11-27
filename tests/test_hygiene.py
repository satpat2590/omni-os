"""The public-hygiene scan and the commit-trailer check that CI runs on every pull request."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_trailers  # noqa: E402
import hygiene  # noqa: E402


def _scan(tmp_path, text, **extra):
    f = tmp_path / "sample.md"
    f.write_text(text)
    return [name for _, _, name, _ in hygiene.scan([str(f)], {**hygiene.CHECKS, **extra})]


@pytest.mark.parametrize("text, finding", [
    ("contact: someone@gmail.com", "personal email"),
    ("db = postgresql://atma:hunter22@127.0.0.1:5432/atma", "credentials in a URL"),
    ("key = sk-ant-" + "a" * 24, "API token"),
    ("cd /Users/alice/omni", "home path"),
    ("ssh into 192.168.1.20", "private address"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private key"),
])
def test_each_kind_of_leak_is_found(tmp_path, text, finding):
    assert _scan(tmp_path, text) == [finding]


@pytest.mark.parametrize("text", [
    "dev@example.com and 1234+bot@users.noreply.github.com",
    'ATMA_DATABASE_URL="postgresql://atma:…@127.0.0.1:5432/atma"',
    "postgresql:///postgres?host=$HOME/pgdata&port=5434",
    "the shared repo at /Users/Shared/omni-os.git",
    "ATMA_TEST_SERVER_URL=postgresql://postgres:${PGPASSWORD}@localhost/postgres",
])
def test_placeholders_and_conventions_are_not_findings(tmp_path, text):
    assert _scan(tmp_path, text) == []


def test_a_machine_can_add_private_patterns_without_publishing_them(tmp_path, monkeypatch):
    patterns = tmp_path / "private.txt"
    patterns.write_text("# owner's names\n\\bAlice\\b\n")
    monkeypatch.setenv("OMNI_HYGIENE_EXTRA", str(patterns))
    assert _scan(tmp_path, "Alice's tasks", **hygiene.extra_patterns()) == ["machine pattern 1"]


def test_the_repository_itself_is_clean():
    os.chdir(ROOT)
    assert hygiene.main([]) == 0


def _git(repo, *args, **env):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", **env}).stdout


def test_trailers_are_required_on_every_change_but_not_on_merges(tmp_path, capsys, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "work")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "good\n\nCard: OMNI-12\nAgent: codex")
    monkeypatch.chdir(repo)
    assert check_trailers.main(["main..work"]) == 0
    _git(repo, "commit", "-q", "--allow-empty", "-m", "no trailers here")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "half\n\nCard: OMNI-3")
    assert check_trailers.main(["main..work"]) == 1
    out = capsys.readouterr().out
    assert "no trailers here" in out and "missing: Card, Agent" in out and "missing: Agent" in out
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge without trailers", "work")
    assert check_trailers.main(["HEAD^1..HEAD^2"]) == 1          # the branch's own commits still count
    assert "merge without trailers" not in capsys.readouterr().out
