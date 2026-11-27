"""The Omni development board: one shared list of what is being built, by whom, on which branch.

Every agent (Claude Code, Codex, OpenCode, Pi, or a person) and every account on the machine uses the
same board, so two of them never build the same thing in silos.

- A card is claimed by exactly one agent at a time; the claim is a single atomic UPDATE.
- Only the agent holding a card moves it, unless it passes --force (which is recorded).
- Every change appends an event. The event records the agent identity (OMNI_AGENT), the OS user,
  and the database role that wrote it, which the server sets and an agent cannot choose.

The board lives in its own Postgres schema, `board`, at OMNI_BOARD_URL (else OMNI_DATABASE_URL, the
ledger's database). Writes require OMNI_AGENT, e.g. "claude-code", "codex", "opencode/omni-dev",
"pi", or "human".
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

MIGRATIONS = Path(__file__).resolve().parents[1] / "board"
STATUSES = ("backlog", "ready", "in_progress", "review", "blocked", "done", "dropped")
OPEN = ("backlog", "ready", "in_progress", "review", "blocked")
SCOPES = ("base", "instance")
_AGENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,59}$")


class BoardError(RuntimeError):
    """A board operation was refused, or the board cannot be reached."""


def dsn(env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env
    url = env.get("OMNI_BOARD_URL") or env.get("OMNI_DATABASE_URL")
    if not url:
        raise BoardError("no board: set OMNI_BOARD_URL (or OMNI_DATABASE_URL); core/bin/omni-svc loads it")
    return url


def agent(env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env
    name = (env.get("OMNI_AGENT") or "").strip().lower()
    if not name:
        raise BoardError("set OMNI_AGENT to who you are (claude-code, codex, opencode/omni-dev, pi, human)")
    if not _AGENT.match(name):
        raise BoardError(f"OMNI_AGENT {name!r}: use lowercase letters, digits and . _ / - (60 max)")
    return name


def card_id(ref) -> int:
    m = re.fullmatch(r"(?i)(?:omni-)?(\d+)", str(ref).strip())
    if not m:
        raise BoardError(f"not a card: {ref!r} (use 12 or OMNI-12)")
    return int(m.group(1))


def key(card: dict) -> str:
    return f"OMNI-{card['id']}"


class Board:
    def __init__(self, url: Optional[str] = None, *, actor: Optional[str] = None):
        self._url = url
        self._actor = actor

    def _connect(self):
        try:
            return psycopg2.connect(self._url or dsn(), connect_timeout=5)
        except psycopg2.Error as exc:
            raise BoardError(f"board unreachable: {str(exc).splitlines()[0]}") from None

    def _actor_name(self) -> str:
        return self._actor or agent()

    def _run(self, fn):
        con = self._connect()
        try:
            with con:
                with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    return fn(cur)
        except psycopg2.errors.UndefinedTable:
            raise BoardError("the board has no tables yet: run `omni board migrate`") from None
        finally:
            con.close()

    def _event(self, cur, cid: int, kind: str, data: Optional[dict] = None) -> None:
        cur.execute("insert into board.events (card_id, os_user, actor, kind, data) values (%s, %s, %s, %s, %s)",
                    (cid, getpass.getuser(), self._actor_name(), kind, json.dumps(data or {})))

    # ---- schema
    def migrate(self) -> list:
        def go(cur):
            cur.execute("create schema if not exists board")
            cur.execute("create table if not exists board.schema_migrations ("
                        "version text primary key, applied_at timestamptz not null default now())")
            cur.execute("select version from board.schema_migrations")
            done = {r["version"] for r in cur.fetchall()}
            applied = []
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.stem in done:
                    continue
                cur.execute(path.read_text())
                cur.execute("insert into board.schema_migrations (version) values (%s)", (path.stem,))
                applied.append(path.name)
            return applied
        return self._run(go)

    # ---- reads
    def list(self, statuses=OPEN, scope: Optional[str] = None, mine: bool = False) -> list:
        def go(cur):
            q = "select * from board.cards where status = any(%s)"
            args = [list(statuses)]
            if scope:
                q += " and scope = %s"
                args.append(scope)
            if mine:
                q += " and assignee = %s"
                args.append(self._actor_name())
            cur.execute(q + " order by array_position(%s, status), priority, id", args + [list(STATUSES)])
            return [dict(r) for r in cur.fetchall()]
        return self._run(go)

    def show(self, ref) -> dict:
        cid = card_id(ref)
        def go(cur):
            cur.execute("select * from board.cards where id = %s", (cid,))
            card = cur.fetchone()
            if not card:
                raise BoardError(f"no card OMNI-{cid}")
            cur.execute("select at, account, os_user, actor, kind, data from board.events "
                        "where card_id = %s order by id", (cid,))
            return dict(card, events=[dict(e) for e in cur.fetchall()])
        return self._run(go)

    # ---- writes
    def add(self, title: str, body: str = "", scope: str = "base", priority: int = 3,
            status: str = "backlog") -> dict:
        if scope not in SCOPES:
            raise BoardError(f"scope must be one of {', '.join(SCOPES)}")
        if status not in ("backlog", "ready"):
            raise BoardError("a new card starts in backlog or ready")
        me = self._actor_name()
        def go(cur):
            cur.execute("insert into board.cards (title, body, scope, priority, status, created_by) "
                        "values (%s, %s, %s, %s, %s, %s) returning *",
                        (title.strip(), body, scope, priority, status, me))
            card = dict(cur.fetchone())
            self._event(cur, card["id"], "created", {"title": card["title"], "scope": scope})
            return card
        return self._run(go)

    def claim(self, ref, branch: Optional[str] = None) -> dict:
        cid, me = card_id(ref), self._actor_name()
        def go(cur):
            cur.execute("update board.cards set assignee = %s, claimed_at = coalesce(claimed_at, now()), "
                        "status = 'in_progress', branch = coalesce(%s, branch), updated_at = now() "
                        "where id = %s and status not in ('done', 'dropped') "
                        "and (assignee is null or assignee = %s) returning *", (me, branch, cid, me))
            card = cur.fetchone()
            if not card:
                cur.execute("select status, assignee from board.cards where id = %s", (cid,))
                now = cur.fetchone()
                if not now:
                    raise BoardError(f"no card OMNI-{cid}")
                if now["assignee"]:
                    raise BoardError(f"OMNI-{cid} is claimed by {now['assignee']}; coordinate there, don't fork the work")
                raise BoardError(f"OMNI-{cid} is {now['status']}")
            self._event(cur, cid, "claimed", {"branch": card["branch"]})
            return dict(card)
        return self._run(go)

    def _holder_check(self, cur, cid: int, force: bool) -> dict:
        cur.execute("select * from board.cards where id = %s for update", (cid,))
        card = cur.fetchone()
        if not card:
            raise BoardError(f"no card OMNI-{cid}")
        if card["assignee"] and card["assignee"] != self._actor_name() and not force:
            raise BoardError(f"OMNI-{cid} is held by {card['assignee']}; only they move it (or use --force, which is recorded)")
        return card

    def move(self, ref, status: str, note: str = "", force: bool = False) -> dict:
        if status not in STATUSES:
            raise BoardError(f"status must be one of {', '.join(STATUSES)}")
        cid = card_id(ref)
        def go(cur):
            card = self._holder_check(cur, cid, force)
            if status == "in_progress" and not card["assignee"]:
                raise BoardError(f"claim OMNI-{cid} to start it (`omni board claim {cid}`)")
            release = status in ("backlog", "ready", "done", "dropped")
            cur.execute("update board.cards set status = %s, updated_at = now()"
                        + (", assignee = null, claimed_at = null" if release else "")
                        + " where id = %s returning *", (status, cid))
            moved = dict(cur.fetchone())
            self._event(cur, cid, "moved", {"from": card["status"], "to": status, "note": note,
                                           "forced": bool(force and card["assignee"] and card["assignee"] != self._actor_name())})
            return moved
        return self._run(go)

    def release(self, ref, note: str = "", force: bool = False) -> dict:
        cid = card_id(ref)
        def go(cur):
            card = self._holder_check(cur, cid, force)
            status = "ready" if card["status"] == "in_progress" else card["status"]
            cur.execute("update board.cards set assignee = null, claimed_at = null, status = %s, updated_at = now() "
                        "where id = %s returning *", (status, cid))
            released = dict(cur.fetchone())
            self._event(cur, cid, "released", {"was": card["assignee"], "note": note})
            return released
        return self._run(go)

    def comment(self, ref, text: str) -> dict:
        cid = card_id(ref)
        if not text.strip():
            raise BoardError("write something")
        def go(cur):
            cur.execute("select id from board.cards where id = %s", (cid,))
            if not cur.fetchone():
                raise BoardError(f"no card OMNI-{cid}")
            cur.execute("update board.cards set updated_at = now() where id = %s", (cid,))
            self._event(cur, cid, "commented", {"text": text.strip()})
            return {"id": cid, "comment": text.strip()}
        return self._run(go)

    def link(self, ref, branch: Optional[str] = None, pr: Optional[str] = None) -> dict:
        cid = card_id(ref)
        if not branch and not pr:
            raise BoardError("give --branch and/or --pr")
        def go(cur):
            cur.execute("update board.cards set branch = coalesce(%s, branch), pr_url = coalesce(%s, pr_url), "
                        "updated_at = now() where id = %s returning *", (branch, pr, cid))
            card = cur.fetchone()
            if not card:
                raise BoardError(f"no card OMNI-{cid}")
            self._event(cur, cid, "linked", {"branch": branch, "pr": pr})
            return dict(card)
        return self._run(go)

    def edit(self, ref, title=None, body=None, priority=None, scope=None) -> dict:
        cid = card_id(ref)
        changes = {k: v for k, v in (("title", title), ("body", body), ("priority", priority), ("scope", scope))
                   if v is not None}
        if not changes:
            raise BoardError("nothing to change")
        if "scope" in changes and changes["scope"] not in SCOPES:
            raise BoardError(f"scope must be one of {', '.join(SCOPES)}")
        def go(cur):
            sets = ", ".join(f"{k} = %s" for k in changes)
            cur.execute(f"update board.cards set {sets}, updated_at = now() where id = %s returning *",
                        (*changes.values(), cid))
            card = cur.fetchone()
            if not card:
                raise BoardError(f"no card OMNI-{cid}")
            self._event(cur, cid, "edited", {k: (v if k != "body" else "(changed)") for k, v in changes.items()})
            return dict(card)
        return self._run(go)


# ---------------------------------------------------------------- command line (`omni board ...`)

def add_arguments(p: argparse.ArgumentParser) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output (for agents)")
    sub = p.add_subparsers(dest="board_cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)
    sub.add_parser("migrate", help="create or update the board's tables")
    ls = sub.add_parser("list", help="open cards (default), or --status ...")
    ls.add_argument("--status", nargs="+", choices=STATUSES)
    ls.add_argument("--scope", choices=SCOPES)
    ls.add_argument("--mine", action="store_true", help="cards held by OMNI_AGENT")
    ls.add_argument("--all", action="store_true", help="include done and dropped")
    sh = sub.add_parser("show")
    sh.add_argument("card")
    ad = sub.add_parser("add")
    ad.add_argument("title")
    ad.add_argument("--body", default="")
    ad.add_argument("--body-file", type=Path)
    ad.add_argument("--scope", choices=SCOPES, default="base")
    ad.add_argument("--priority", type=int, default=3, choices=range(1, 6))
    ad.add_argument("--ready", action="store_true", help="start in ready instead of backlog")
    cl = sub.add_parser("claim", help="take a card; you alone move it until you release it")
    cl.add_argument("card")
    cl.add_argument("--branch")
    rl = sub.add_parser("release")
    rl.add_argument("card")
    rl.add_argument("--note", default="")
    rl.add_argument("--force", action="store_true")
    mv = sub.add_parser("move")
    mv.add_argument("card")
    mv.add_argument("status", choices=STATUSES)
    mv.add_argument("--note", default="")
    mv.add_argument("--force", action="store_true")
    cm = sub.add_parser("comment")
    cm.add_argument("card")
    cm.add_argument("text")
    ln = sub.add_parser("link")
    ln.add_argument("card")
    ln.add_argument("--branch")
    ln.add_argument("--pr")
    ed = sub.add_parser("edit")
    ed.add_argument("card")
    ed.add_argument("--title")
    ed.add_argument("--body")
    ed.add_argument("--priority", type=int, choices=range(1, 6))
    ed.add_argument("--scope", choices=SCOPES)


def _line(c: dict) -> str:
    who = f"  @{c['assignee']}" if c.get("assignee") else ""
    where = f"  [{c['branch']}]" if c.get("branch") else ""
    return f"{key(c):<9} {c['status']:<12} p{c['priority']} {c['scope']:<8} {c['title']}{who}{where}"


def _print(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, default=str, indent=2))
    elif isinstance(result, list):
        print("\n".join(_line(c) for c in result) if result else "(no cards)")
    elif "events" in result:
        print(_line(result))
        if result.get("body"):
            print("\n" + result["body"].rstrip() + "\n")
        for e in result["events"]:
            detail = {k: v for k, v in (e["data"] or {}).items() if v not in (None, "", False)}
            print(f"  {str(e['at'])[:16]}  {e['actor']}@{e['account']}  {e['kind']}"
                  + (f"  {json.dumps(detail, ensure_ascii=False)}" if detail else ""))
    elif "title" in result:
        print(_line(result))
    else:
        print(json.dumps(result, default=str))


def run(opts, board: Optional[Board] = None) -> int:
    board = board or Board()
    try:
        c = opts.board_cmd
        if c == "migrate":
            applied = board.migrate()
            print("applied: " + (", ".join(applied) or "nothing (up to date)"))
            return 0
        if c == "list":
            statuses = opts.status or (STATUSES if opts.all else OPEN)
            result = board.list(statuses, opts.scope, opts.mine)
        elif c == "show":
            result = board.show(opts.card)
        elif c == "add":
            body = opts.body_file.read_text() if opts.body_file else opts.body
            result = board.add(opts.title, body, opts.scope, opts.priority, "ready" if opts.ready else "backlog")
        elif c == "claim":
            result = board.claim(opts.card, opts.branch)
        elif c == "release":
            result = board.release(opts.card, opts.note, opts.force)
        elif c == "move":
            result = board.move(opts.card, opts.status, opts.note, opts.force)
        elif c == "comment":
            result = board.comment(opts.card, opts.text)
        elif c == "link":
            result = board.link(opts.card, opts.branch, opts.pr)
        elif c == "edit":
            result = board.edit(opts.card, opts.title, opts.body, opts.priority, opts.scope)
        else:
            raise BoardError(f"unknown board command {c}")
    except BoardError as exc:
        print(f"omni board: {exc}", file=sys.stderr)
        return 2
    _print(result, opts.json)
    return 0
