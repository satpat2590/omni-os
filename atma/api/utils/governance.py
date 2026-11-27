"""Atma's rules own classification, scoring and taxonomy mutations."""
from difflib import SequenceMatcher
import json
import re

from .db import db

from .taxonomy import CATALOG, REVISION, lookup

LOCK = "LOCK TABLE tags IN SHARE ROW EXCLUSIVE MODE"


def suggest(task):
    return lookup(task.title, task.description, task.category)


def normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def resolve_tag(cur, category, path):
    # Catalog nodes can move. Anchor at the deepest label that still
    # identifies one catalog path and one tag in this category.
    cur.execute("SELECT id,name FROM tags WHERE category=%s", (category,))
    ids_by_name = {}
    for row in cur.fetchall():
        ids_by_name.setdefault(normalized(row["name"]), []).append(row["id"])
    catalog = CATALOG[category]
    parent = None
    remaining = path
    for depth in range(len(path), 0, -1):
        prefix = tuple(path[:depth])
        if prefix not in catalog:
            continue
        name = prefix[-1]
        ids = ids_by_name.get(normalized(name), [])
        if len(ids) == 1 and sum(p[-1] == name for p in catalog) == 1:
            parent = ids[0]
            remaining = path[depth:]
            break
    for name in remaining:
        cur.execute("SELECT id,name FROM tags WHERE category=%s AND parent_tag_id IS NOT DISTINCT FROM %s ORDER BY id", (category, parent))
        candidates = cur.fetchall()
        target = normalized(name)
        matches = [(SequenceMatcher(None, target, normalized(row["name"])).ratio(), -row["id"]) for row in candidates]
        if matches and max(matches)[0] >= 0.92:
            parent = -max(matches)[1]
        else:
            cur.execute("INSERT INTO tags(name,category,parent_tag_id,auto_created) VALUES (%s,%s,%s,true) RETURNING id", (name, category, parent))
            parent = cur.fetchone()["id"]
    return parent


def create(task, assigned, creator):
    category, path, method = suggest(task)
    with db.cursor() as cur:
        cur.execute(LOCK)
        tag = resolve_tag(cur, category, path) if path else None
        cur.execute("""INSERT INTO tasks(title,description,category,priority,due_date,is_recurring,
                       recurrence_pattern,assigned_to,created_by,classification) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING *""", (task.title,task.description,category,task.priority,task.due_date,
                       task.is_recurring,task.recurrence_pattern,assigned,creator,
                       json.dumps({"method": method, "tag_id": tag, "path": path, "policy_version": 2, "catalog_revision": REVISION, "assigned_category": category, "hint": task.category, "input_title": task.title, "input_description": task.description})))
        row = dict(cur.fetchone())
        if tag is not None:
            cur.execute("INSERT INTO task_tags(task_id,tag_id) VALUES (%s,%s)", (row["id"], tag))
        return row


def move(tag, parent):
    with db.cursor() as cur:
        cur.execute(LOCK)
        cur.execute("SELECT id,category,name FROM tags WHERE id=%s", (tag,))
        node = cur.fetchone()
        if not node:
            raise ValueError("Unknown tag")
        if parent is not None:
            cur.execute("""WITH RECURSIVE ancestors AS (
                SELECT id,parent_tag_id,category FROM tags WHERE id=%s UNION
                SELECT t.id,t.parent_tag_id,t.category FROM tags t JOIN ancestors a ON t.id=a.parent_tag_id)
                SELECT id,category FROM ancestors""", (parent,))
            ancestors = cur.fetchall()
            if not ancestors or any(a["category"] != node["category"] or a["id"] == tag for a in ancestors):
                raise ValueError("Parent must be in the same root and outside the subtree")
        cur.execute("SELECT name FROM tags WHERE category=%s AND parent_tag_id IS NOT DISTINCT FROM %s AND id<>%s", (node["category"], parent, tag))
        if any(normalized(r["name"]) == normalized(node["name"]) for r in cur.fetchall()):
            raise ValueError("Destination already has a tag with that name")
        cur.execute("UPDATE tags SET parent_tag_id=%s WHERE id=%s", (parent,tag))
        return {"id": tag, "parent_tag_id": parent}
