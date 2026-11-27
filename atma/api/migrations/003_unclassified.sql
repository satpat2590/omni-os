-- Keep legacy domain values valid. Unclassified is an inbox state, outside the four roots.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_constraint WHERE conrelid='public.tasks'::regclass AND conname='tasks_category_check') THEN
    ALTER TABLE public.tasks DROP CONSTRAINT tasks_category_check;
    ALTER TABLE public.tasks ADD CONSTRAINT tasks_category_check
      CHECK (category IN ('mental','physical','social','financial','omni','whoop','veltiosi','argus','unclassified'));
  END IF;
END $$;
