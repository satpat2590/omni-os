"""The development board on a real Postgres: one claimant per card, history no agent can forge.

Runs against a brand-new database on OMNI_TEST_SERVER_URL (a local server only) and drops it after.
Skips without one.
"""
import argparse
import io
import json
import os
import uuid
from contextlib import redirect_stdout

import psycopg2
import pytest
from psycopg2.extensions import make_dsn, parse_dsn

from omni_core import board as board_mod
from omni_core.board import Board, BoardError

SERVER = os.environ.get("OMNI_TEST_SERVER_URL")


@pytest.fixture(scope="module")
def url():
    if not SERVER:
        pytest.skip("OMNI_TEST_SERVER_URL is not set: no local Postgres to test against")
    parts = parse_dsn(SERVER)
    host = parts.get("host", "")
    if host and not (host.startswith("/") or host in ("localhost", "127.0.0.1", "::1")):
        raise pytest.UsageError("OMNI_TEST_SERVER_URL must be a local server")
    name = f"omni_board_test_{uuid.uuid4().hex[:10]}"
    admin = psycopg2.connect(SERVER)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'create database "{name}"')
    dsn = make_dsn(**{**parts, "dbname": name})
    assert Board(dsn, actor="test").migrate() == ["001_board.sql"]
    yield dsn
    with admin.cursor() as cur:
        cur.execute(f'drop database if exists "{name}" with (force)')
    admin.close()


def as_(url, who):
    return Board(url, actor=who)


def test_migrate_is_idempotent(url):
    assert as_(url, "test").migrate() == []


def test_a_card_has_one_claimant_and_only_it_moves_the_card(url):
    claude, codex = as_(url, "claude-code"), as_(url, "codex")
    card = claude.add("Fix migration 003 categories", scope="base", priority=2)
    assert card["status"] == "backlog" and card["created_by"] == "claude-code"

    claimed = codex.claim(card["id"], branch="agent/codex/omni-1")
    assert claimed["assignee"] == "codex" and claimed["status"] == "in_progress"
    with pytest.raises(BoardError, match="claimed by codex"):
        claude.claim(card["id"])
    assert codex.claim(f"OMNI-{card['id']}")["assignee"] == "codex"          # re-claim by the holder is fine
    with pytest.raises(BoardError, match="held by codex"):
        claude.move(card["id"], "review")

    codex.move(card["id"], "review", note="PR open")
    forced = claude.move(card["id"], "blocked", note="CI red", force=True)
    assert forced["status"] == "blocked"
    done = codex.move(card["id"], "done")
    assert done["assignee"] is None and done["claimed_at"] is None           # done releases the claim

    events = codex.show(card["id"])["events"]
    assert [e["kind"] for e in events] == ["created", "claimed", "claimed", "moved", "moved", "moved"]
    assert events[4]["actor"] == "claude-code" and events[4]["data"]["forced"] is True
    assert all(e["account"] for e in events)                                  # set by the server, not the agent
    with pytest.raises(BoardError, match="is done"):
        codex.claim(card["id"])


def test_release_returns_an_in_progress_card_to_ready(url):
    pi = as_(url, "pi")
    card = pi.add("Write the omni-test skill", status="ready")
    pi.claim(card["id"])
    released = pi.release(card["id"], note="handing to opencode")
    assert released["status"] == "ready" and released["assignee"] is None
    with pytest.raises(BoardError, match="claim"):
        pi.move(card["id"], "in_progress")


def test_list_filters_and_orders_open_cards(url):
    b = as_(url, "opencode/omni-dev")
    urgent = b.add("Urgent instance fix", scope="instance", priority=1, status="ready")
    b.claim(urgent["id"])
    titles = [c["title"] for c in b.list(scope="instance")]
    assert "Urgent instance fix" in titles
    assert all(c["scope"] == "instance" for c in b.list(scope="instance"))
    assert [c["id"] for c in b.list(mine=True)] == [urgent["id"]]
    assert all(c["status"] not in ("done", "dropped") for c in b.list())


def test_comments_links_and_edits_are_recorded(url):
    b = as_(url, "human")
    card = b.add("Board docs")
    b.comment(card["id"], "see AGENTS.md")
    b.link(card["id"], branch="agent/human/board-docs", pr="https://github.com/example/pr/1")
    edited = b.edit(card["id"], title="Board docs, final", priority=4)
    assert edited["title"] == "Board docs, final" and edited["pr_url"].endswith("/pr/1")
    assert [e["kind"] for e in b.show(card["id"])["events"]] == ["created", "commented", "linked", "edited"]
    with pytest.raises(BoardError, match="give --branch"):
        b.link(card["id"])


def test_writes_need_an_agent_identity(url, monkeypatch):
    monkeypatch.delenv("OMNI_AGENT", raising=False)
    with pytest.raises(BoardError, match="OMNI_AGENT"):
        Board(url).add("anonymous")
    monkeypatch.setenv("OMNI_AGENT", "Not Valid!")
    with pytest.raises(BoardError, match="lowercase"):
        Board(url).add("bad name")
    with pytest.raises(BoardError, match="not a card"):
        Board(url, actor="x").show("OMNI-abc")


def test_cli_json_output_for_agents(url, monkeypatch):
    monkeypatch.setenv("OMNI_BOARD_URL", url)
    monkeypatch.setenv("OMNI_AGENT", "codex")
    parser = argparse.ArgumentParser()
    board_mod.add_arguments(parser)

    def cli(*argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = board_mod.run(parser.parse_args(list(argv)))
        return code, out.getvalue()

    code, out = cli("add", "From the CLI", "--ready", "--json")
    assert code == 0
    cid = json.loads(out)["id"]
    code, out = cli("claim", str(cid), "--branch", "agent/codex/cli", "--json")
    assert code == 0 and json.loads(out)["assignee"] == "codex"
    code, out = cli("list", "--mine", "--json")
    assert cid in [c["id"] for c in json.loads(out)]
    monkeypatch.setenv("OMNI_AGENT", "claude-code")
    code, _ = cli("claim", str(cid))
    assert code == 2                                                          # refused, not a crash
