-- The Omni development board: what is being built, by whom, on which branch.
-- One board is shared by every account and every agent on the machine, so no work happens in a silo.
create schema if not exists board;

create table if not exists board.cards (
    id          bigserial   primary key,
    title       text        not null check (length(btrim(title)) between 1 and 200),
    body        text        not null default '',
    status      text        not null default 'backlog'
                check (status in ('backlog', 'ready', 'in_progress', 'review', 'blocked', 'done', 'dropped')),
    scope       text        not null default 'base' check (scope in ('base', 'instance')),
    priority    integer     not null default 3 check (priority between 1 and 5),   -- 1 = most urgent
    assignee    text,                    -- the agent holding the claim; null = free
    claimed_at  timestamptz,
    branch      text,
    pr_url      text,
    created_by  text        not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    check ((assignee is null) = (claimed_at is null))
);

create index if not exists cards_open on board.cards (status, priority, id)
    where status not in ('done', 'dropped');

-- Append-only history. `account` is the database role that wrote the row, set by the server, so an
-- agent cannot write as another account. `actor` is the agent identity it declared (OMNI_AGENT).
create table if not exists board.events (
    id       bigserial   primary key,
    card_id  bigint      not null references board.cards (id),
    at       timestamptz not null default now(),
    account  text        not null default current_user,
    os_user  text        not null,
    actor    text        not null,
    kind     text        not null
             check (kind in ('created', 'edited', 'claimed', 'released', 'moved', 'commented', 'linked')),
    data     jsonb       not null default '{}'::jsonb
);

create index if not exists events_card on board.events (card_id, id);
