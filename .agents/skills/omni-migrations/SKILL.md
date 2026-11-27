---
name: omni-migrations
description: Rules and steps for changing a database schema in Omni OS (Atma's database, core's run ledger, or the development board). Use whenever a change adds, alters or removes tables, columns, constraints, views or triggers.
---

# Schema changes

Omni has three schemas, each with its own numbered migrations and runner:

| Database | Migrations | Applied by | Recorded in |
|---|---|---|---|
| Atma | `atma/api/migrations/NNN_name.sql` | `atma/api/scripts/migrate.py` | `public.schema_migrations` |
| Core run ledger | `core/migrations/NNN_name.sql` | `omni migrate` | nothing: every file re-runs each time, so each **must** be idempotent |
| Development board | `core/board/NNN_name.sql` | `omni board migrate` | `board.schema_migrations` |

## Rules

1. **Append-only.** Never edit or renumber a migration once it is on `main`: some database has
   run it. Fix a mistake with the next number.
2. **Both starting points.** Each migration must apply to an empty database and to an existing
   one. The test fixtures build every database from all the migrations, so an empty database is
   tested on every run. For an existing database, write a test that sets up the old shape and
   migrates it, as `atma/api/tests/test_migrate.py` does.
3. **Plain SQL that psycopg2 can run.** No `psql` meta-commands (`\restrict`, `\connect`, `\i`).
   `pg_dump` adds some; strip them.
4. **Base values only.** A constraint or default in base must not name a person or one machine's
   domains. `tasks.category` allows the four roots (`physical`, `mental`, `financial`, `social`)
   and `unclassified`. An instance that needs more adds its own migration on its instance branch,
   numbered high (for example `900_instance_categories.sql`), so base numbering never collides
   with it.
5. **Qualify names** (`public.tasks`, `core.runs`, `board.cards`). Migrations can run with an
   empty `search_path`.
6. **Idempotent where it's cheap** (`if not exists`, `on conflict do nothing`). The Atma and board
   runners apply each file once, but a hand-run during recovery should be harmless. Core's ledger
   migrations re-run on every `omni migrate`, so they must be idempotent.
7. **No data destruction** without a card that says so and an owner who approved it. Dropping a
   column that holds data needs a backup step on the card.

## Steps

```bash
ls atma/api/migrations                 # the next number
$EDITOR atma/api/migrations/006_short_name.sql
(cd atma/api && ATMA_TEST_SERVER_URL=... .venv/bin/python -m pytest -q tests/test_migrate.py)
```

Add or extend a test that exercises the new column or constraint. The live instance applies the
migration when the operator merges and runs the migrations (`omni-release`). Base never touches a
live database.
