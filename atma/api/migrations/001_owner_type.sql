-- The human owner's tasks are owner_type 'owner'. Databases created before Omni OS used a person's
-- name as that value; convert them. Safe to re-run: on a fresh database it changes nothing.
ALTER TABLE public.tasks ALTER COLUMN owner_type SET DEFAULT 'owner';
UPDATE public.tasks SET owner_type = 'owner' WHERE owner_type IS DISTINCT FROM 'agent' AND owner_type IS NOT NULL
    AND owner_type <> 'owner';
