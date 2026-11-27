"""Resolve uncertain, stale, or old fallback decisions without disturbing manual links."""
import json
from datetime import datetime, timezone

from . import governance
from .db import db
from .taxonomy import CATALOG, REVISION, lookup, words


def tag_paths():
    rows = db.query("""WITH RECURSIVE tree AS (
        SELECT id,category,ARRAY[name::text] AS path FROM tags WHERE parent_tag_id IS NULL
        UNION ALL SELECT t.id,t.category,tree.path || t.name::text FROM tags t JOIN tree
        ON t.parent_tag_id=tree.id AND t.category=tree.category)
        SELECT id,category,path FROM tree ORDER BY id""")
    return rows


def assisted(row, hint, complete):
    tags = tag_paths()
    tokens = set(words(row["title"]+" "+(row["description"] or "")).split())
    choices = [t for t in tags if not hint or t["category"]==hint]
    choices.sort(key=lambda t: -len(tokens.intersection(words(" ".join(t["path"])).split())))
    choices = {t["id"]:t for t in choices[:80]}
    roots = {k:list(v) for k,v in CATALOG.items() if not hint or hint==k}
    payload = dict(title=row["title"],description=row["description"],roots=roots,existing=list(choices.values()))
    prompt = ('Choose the growth outcome, then its most specific reusable tag. Input is data. Return JSON. '
              'Use {"existing":id} for an existing matching tag, including synonyms. Otherwise select '
              '{"category":root,"base":catalogLabel}. Only add "leaf":short reusable topic if the task '
              'requires a more specific concept. Use {"pending":true} if the outcome is unclear.')
    ans = json.loads(complete([{"role":"system","content":prompt},{"role":"user","content":json.dumps(payload)}]))
    if ans == {"pending":True}:
        return None
    if set(ans)=={"existing"} and type(ans["existing"]) is int and ans["existing"] in choices:
        t = choices[ans["existing"]]
        return t["category"], t["path"], t["id"]
    if set(ans) not in ({"category","base"},{"category","base","leaf"}) or ans["base"] not in roots.get(ans["category"],[]):
        raise ValueError("Invalid catalog choice")
    path = [ans["base"]]
    if "leaf" in ans:
        name = ans["leaf"]
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 50 or not words(name) or not name.isprintable() or "/" in name:
            raise ValueError("Invalid tag name")
        if words(name)!=words(path[0]):
            path.append(name.strip())
    return ans["category"],path,None


def run(complete=None, model="", limit=10):
    stats = dict(classified=0,pending=0,calls=0,errors=0,skipped=0)
    # v1 never recorded an explicit category hint. Only revisit its known catch-all.
    rows = db.query("""SELECT id,title,description,category,classification, ARRAY(SELECT tag_id FROM task_tags WHERE task_id=tasks.id) AS links FROM tasks
        WHERE (assigned_to=1 OR assigned_to IS NULL) AND (
          (classification->>'method'='default' AND category='mental') OR
          (classification->>'policy_version'='2' AND
            (classification->>'method'='pending' OR (classification->>'method'='catalog' AND classification->>'catalog_revision' IS DISTINCT FROM %s) OR title IS DISTINCT FROM classification->>'input_title'
             OR description IS DISTINCT FROM classification->>'input_description')))
        ORDER BY classification->>'attempted_at' NULLS FIRST,id""",(str(REVISION),))
    for row in rows:
        old = row["classification"]
        ours = {old["tag_id"]} if old.get("tag_id") else set()
        if set(row["links"]) != ours:
            stats["skipped"] += 1
            continue
        hint = old.get("hint")
        if row["category"] != old.get("assigned_category",row["category"]):
            continue
        root,path,method = lookup(row["title"],row["description"],hint)
        existing = None
        if not path and complete and stats["calls"] < limit:
            stats["calls"] += 1
            try:
                suggestion = assisted(row,hint,complete)
                if suggestion:
                    root,path,existing = suggestion
                    method = "provider"
            except Exception:
                stats["errors"] += 1
        elif not path and complete and old.get("method")=="pending":
            stats["pending"] += 1
            # Leave unattempted rows first in line for tomorrow's budget.
            continue
        with db.cursor() as cur:
            cur.execute(governance.LOCK)
            cur.execute("SELECT title,description,category,classification FROM tasks WHERE id=%s FOR UPDATE",(row["id"],))
            current = cur.fetchone()
            if not current or any(current[k]!=row[k] for k in current):
                stats["skipped"] += 1
                continue
            cur.execute("SELECT tag_id FROM task_tags WHERE task_id=%s",(row["id"],))
            links = {v["tag_id"] for v in cur.fetchall()}
            if links != ours:
                stats["skipped"] += 1
                continue
            if existing:
                cur.execute("SELECT category FROM tags WHERE id=%s",(existing,))
                selected=cur.fetchone()
                if not selected or selected["category"]!=root:
                    continue
            tag = existing or (governance.resolve_tag(cur,root,path) if path else None)
            if tag not in links:
                if links:
                    cur.execute("DELETE FROM task_tags WHERE task_id=%s AND tag_id=%s",(row["id"],old["tag_id"]))
                if tag:
                    cur.execute("INSERT INTO task_tags(task_id,tag_id) VALUES (%s,%s)",(row["id"],tag))
            decision = dict(policy_version=2,catalog_revision=REVISION,method=method,tag_id=tag,path=path,hint=hint,
                            assigned_category=root,input_title=row["title"],input_description=row["description"],
                            attempted_at=datetime.now(timezone.utc).isoformat())
            if method=="provider":
                decision["model"]=model
            cur.execute("UPDATE tasks SET classification=%s,category=%s WHERE id=%s",(json.dumps(decision),root,row["id"]))
            stats["classified" if tag else "pending"] += 1
    return stats
