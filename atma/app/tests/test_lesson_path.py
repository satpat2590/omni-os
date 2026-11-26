"""Tests for the lesson viewer's path guard.

/api/gyani/lesson is served publicly, so it must only ever return curriculum
markdown — never another file under home, and never anything outside it.
"""

import json

import pytest

from app import routes_gyani


@pytest.fixture
def home(tmp_path, monkeypatch):
    curriculum = tmp_path / "Obsidian" / "Curriculum"
    (curriculum / "finance").mkdir(parents=True)
    (curriculum / "finance" / "lesson.md").write_text("# Lesson\n")
    (tmp_path / "Obsidian" / "private.md").write_text("vault, not curriculum")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "notes.md").write_text("home markdown")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(routes_gyani, "OBSIDIAN_CURRICULUM", curriculum)
    return tmp_path


def _status(resp):
    return getattr(resp, "status_code", 200)


def test_serves_curriculum_lesson(home):
    out = routes_gyani.gyani_lesson_content("Obsidian/Curriculum/finance/lesson.md")
    assert out["content"] == "# Lesson\n"


@pytest.mark.parametrize("path", [
    ".env",                                            # non-markdown under home
    "notes.md",                                        # markdown outside the curriculum
    "Obsidian/private.md",                             # vault, but not curriculum
    "Obsidian/Curriculum/../private.md",               # lexically inside, escapes on resolve
    "Obsidian/Curriculum/finance/../../../.env",
    "../../etc/shells",                                # outside home
    "/etc/shells",                                     # absolute path replaces home
])
def test_rejects_paths_outside_curriculum(home, path):
    resp = routes_gyani.gyani_lesson_content(path)
    assert _status(resp) == 404
    assert json.loads(resp.body) == {"error": "not found"}


def test_rejects_symlink_out_of_curriculum(home):
    link = home / "Obsidian" / "Curriculum" / "finance" / "leak.md"
    link.symlink_to(home / ".env")
    assert _status(routes_gyani.gyani_lesson_content("Obsidian/Curriculum/finance/leak.md")) == 404
