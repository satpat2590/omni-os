# Atma migrations

`scripts/migrate.py` applies these in number order, once each, and records them in
`public.schema_migrations`.

| File | What it does |
|---|---|
| `000_base.sql` | Creates Atma from nothing: 13 tables, 3 views, and the `tasks.updated_at` trigger. It was generated from the live schema with Supabase's RLS policies and a non-Atma table removed. |
| `001_owner_type.sql` | Makes the human owner's `tasks.owner_type` the value `owner`, in databases from before Omni OS. |

```bash
python3 scripts/migrate.py --status        # applied and pending, change nothing
python3 scripts/migrate.py                 # apply what is pending to $ATMA_DATABASE_URL
python3 scripts/migrate.py --baseline      # an existing Atma database: record 000 as applied
```

Each new change to the schema is a new file, `NNN_short_name.sql`, numbered one past the last.
Migrations are never edited after they have been applied anywhere. They are plain SQL that `psycopg2`
can run as a single statement batch, with no `psql` meta-commands (`\restrict`, `\connect`, …).

The tests build a fresh database from these files for every run (see `tests/conftest.py`), so a
migration that doesn't apply cleanly to an empty database fails the test suite.
