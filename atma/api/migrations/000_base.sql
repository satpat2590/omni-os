-- Atma base schema for Omni OS (baseline, migration 000).
--
-- Generated 2026-11-26 from the live Atma database's schema (pg_dump --schema-only), with what
-- was not Atma removed: Supabase's permissive RLS policies, a table that belonged to another
-- domain, and a fifth task category. Apply to an empty database:
--     psql "$ATMA_DATABASE_URL" -v ON_ERROR_STOP=1 -f 000_base.sql
-- or run atma/api/scripts/migrate.py, which records it in schema_migrations.

--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_domains (
    agent_id integer NOT NULL,
    tag_id integer NOT NULL
);


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    category character varying(20),
    priority integer DEFAULT 3,
    due_date timestamp with time zone,
    is_recurring boolean DEFAULT false,
    recurrence_pattern character varying(20),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    chain_group character varying(50),
    assigned_to integer,
    created_by integer,
    verification jsonb,
    owner_type character varying DEFAULT 'owner'::character varying,
    routing_state character varying,
    CONSTRAINT tasks_category_check CHECK (((category)::text = ANY ((ARRAY['mental'::character varying, 'physical'::character varying, 'social'::character varying, 'financial'::character varying, 'omni'::character varying, 'whoop'::character varying, 'veltiosi'::character varying, 'argus'::character varying])::text[]))),
    CONSTRAINT tasks_priority_check CHECK (((priority >= 1) AND (priority <= 5)))
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    name text NOT NULL,
    user_type text DEFAULT 'human'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT users_user_type_check CHECK ((user_type = ANY (ARRAY['human'::text, 'agent'::text])))
);


--
-- Name: agent_task_queue; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.agent_task_queue AS
 SELECT t.id,
    t.title,
    t.category,
    t.priority,
    t.is_active,
    t.due_date,
    t.assigned_to,
    u.name AS assigned_to_name,
    u.user_type AS assigned_to_type,
    t.created_by,
    cu.name AS created_by_name
   FROM ((public.tasks t
     JOIN public.users u ON ((t.assigned_to = u.id)))
     JOIN public.users cu ON ((t.created_by = cu.id)))
  WHERE (t.is_active = true)
  ORDER BY t.priority DESC, t.created_at DESC;


--
-- Name: task_completions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_completions (
    id integer NOT NULL,
    task_id integer,
    completed_at timestamp with time zone DEFAULT now(),
    completion_quality integer,
    notes text,
    was_late boolean DEFAULT false,
    time_spent_minutes integer,
    points smallint DEFAULT '0'::smallint,
    CONSTRAINT task_completions_completion_quality_check CHECK (((completion_quality >= 1) AND (completion_quality <= 5)))
);


--
-- Name: COLUMN task_completions.points; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_completions.points IS 'The amount of points that were either added/deducted from the task completion';


--
-- Name: daily_stats; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.daily_stats AS
 SELECT date(task_completions.completed_at) AS date,
    count(*) AS tasks_completed,
    avg(task_completions.completion_quality) AS avg_quality,
    sum(
        CASE
            WHEN task_completions.was_late THEN 1
            ELSE 0
        END) AS late_tasks
   FROM public.task_completions
  GROUP BY (date(task_completions.completed_at));


--
-- Name: growth_scores_28d; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.growth_scores_28d AS
SELECT
    NULL::integer AS task_id,
    NULL::character varying(255) AS title,
    NULL::character varying(20) AS category,
    NULL::integer AS priority,
    NULL::integer AS assigned_to,
    NULL::bigint AS completions_28d,
    NULL::numeric AS expected_28d,
    NULL::bigint AS pos_pts_28d,
    NULL::timestamp with time zone AS last_completed,
    NULL::numeric AS missed_28d,
    NULL::numeric AS growth_score;


--
-- Name: VIEW growth_scores_28d; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.growth_scores_28d IS 'Windowed (28d) growth score per active task. Drives mindmap/dashboard color. Spec: SPEC-growth-system-revamp-2026-08.';


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    task_id integer,
    sent_at timestamp with time zone DEFAULT now(),
    notification_type character varying(20),
    channel character varying(10),
    CONSTRAINT notifications_channel_check CHECK (((channel)::text = ANY ((ARRAY['email'::character varying, 'sms'::character varying, 'both'::character varying])::text[]))),
    CONSTRAINT notifications_notification_type_check CHECK (((notification_type)::text = ANY ((ARRAY['reminder'::character varying, 'overdue'::character varying, 'punishment'::character varying, 'summary'::character varying])::text[])))
);


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;


--
-- Name: punishment_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.punishment_rules (
    id integer NOT NULL,
    hours_overdue integer NOT NULL,
    action character varying(50) NOT NULL,
    is_active boolean DEFAULT true
);


--
-- Name: punishment_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.punishment_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: punishment_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.punishment_rules_id_seq OWNED BY public.punishment_rules.id;


--
-- Name: self_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.self_assessments (
    id integer NOT NULL,
    task_id integer,
    decision character varying NOT NULL,
    had_gap boolean NOT NULL,
    gap_tags jsonb,
    gap_magnitude real,
    recommended_agent character varying,
    chosen_agent character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: self_assessments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.self_assessments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: self_assessments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.self_assessments_id_seq OWNED BY public.self_assessments.id;


--
-- Name: tag_dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_dependencies (
    tag_id integer NOT NULL,
    depends_on_tag_id integer NOT NULL,
    required_proficiency real DEFAULT 3.0
);


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tags (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    parent_tag_id integer,
    category character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    required_proficiency real DEFAULT 3.0,
    auto_created boolean DEFAULT false NOT NULL
);


--
-- Name: tags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tags_id_seq OWNED BY public.tags.id;


--
-- Name: task_completions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_completions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_completions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_completions_id_seq OWNED BY public.task_completions.id;


--
-- Name: task_delegations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_delegations (
    id integer NOT NULL,
    task_id integer,
    from_user integer,
    to_user integer,
    routing_decision character varying NOT NULL,
    rationale text,
    kanban_task_id text,
    state character varying DEFAULT 'delegated'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


--
-- Name: task_delegations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_delegations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_delegations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_delegations_id_seq OWNED BY public.task_delegations.id;


--
-- Name: task_skill_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_skill_requirements (
    task_id integer NOT NULL,
    tag_id integer NOT NULL,
    required_proficiency real DEFAULT 3.0
);


--
-- Name: task_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_tags (
    task_id integer NOT NULL,
    tag_id integer NOT NULL
);


--
-- Name: tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tasks_id_seq OWNED BY public.tasks.id;


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.verifications (
    id integer NOT NULL,
    task_id integer,
    tag_id integer,
    lesson_path text,
    state text DEFAULT 'in_progress'::text NOT NULL,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    completed_at timestamp without time zone,
    quality integer,
    max_level_reached integer,
    proficiency_notes text,
    questions jsonb,
    transcript jsonb,
    penalty_applied boolean DEFAULT false,
    created_by text DEFAULT 'gyani'::text,
    submissions jsonb,
    submission_reviewed_at timestamp without time zone,
    CONSTRAINT verifications_quality_check CHECK (((quality >= 1) AND (quality <= 5))),
    CONSTRAINT verifications_state_check CHECK ((state = ANY (ARRAY['in_progress'::text, 'passed'::text, 'failed'::text, 'abandoned'::text])))
);


--
-- Name: COLUMN verifications.submissions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.verifications.submissions IS 'Artifact submissions from Google Drive: [{file_id, name, mime, web_link, submitted_at, assessment}]';


--
-- Name: verifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.verifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: verifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.verifications_id_seq OWNED BY public.verifications.id;


--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);


--
-- Name: punishment_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.punishment_rules ALTER COLUMN id SET DEFAULT nextval('public.punishment_rules_id_seq'::regclass);


--
-- Name: self_assessments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.self_assessments ALTER COLUMN id SET DEFAULT nextval('public.self_assessments_id_seq'::regclass);


--
-- Name: tags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags ALTER COLUMN id SET DEFAULT nextval('public.tags_id_seq'::regclass);


--
-- Name: task_completions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_completions ALTER COLUMN id SET DEFAULT nextval('public.task_completions_id_seq'::regclass);


--
-- Name: task_delegations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_delegations ALTER COLUMN id SET DEFAULT nextval('public.task_delegations_id_seq'::regclass);


--
-- Name: tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks ALTER COLUMN id SET DEFAULT nextval('public.tasks_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: verifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verifications ALTER COLUMN id SET DEFAULT nextval('public.verifications_id_seq'::regclass);


--
-- Name: agent_domains agent_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_domains
    ADD CONSTRAINT agent_domains_pkey PRIMARY KEY (agent_id, tag_id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: punishment_rules punishment_rules_hours_overdue_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.punishment_rules
    ADD CONSTRAINT punishment_rules_hours_overdue_key UNIQUE (hours_overdue);


--
-- Name: punishment_rules punishment_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.punishment_rules
    ADD CONSTRAINT punishment_rules_pkey PRIMARY KEY (id);


--
-- Name: self_assessments self_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.self_assessments
    ADD CONSTRAINT self_assessments_pkey PRIMARY KEY (id);


--
-- Name: tag_dependencies tag_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_dependencies
    ADD CONSTRAINT tag_dependencies_pkey PRIMARY KEY (tag_id, depends_on_tag_id);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);


--
-- Name: task_completions task_completions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_completions
    ADD CONSTRAINT task_completions_pkey PRIMARY KEY (id);


--
-- Name: task_delegations task_delegations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_delegations
    ADD CONSTRAINT task_delegations_pkey PRIMARY KEY (id);


--
-- Name: task_skill_requirements task_skill_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_skill_requirements
    ADD CONSTRAINT task_skill_requirements_pkey PRIMARY KEY (task_id, tag_id);


--
-- Name: task_tags task_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_tags
    ADD CONSTRAINT task_tags_pkey PRIMARY KEY (task_id, tag_id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: users users_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_name_key UNIQUE (name);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: verifications verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verifications
    ADD CONSTRAINT verifications_pkey PRIMARY KEY (id);


--
-- Name: idx_completions_task_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_completions_task_date ON public.task_completions USING btree (task_id, completed_at);


--
-- Name: idx_self_assessments_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_self_assessments_created ON public.self_assessments USING btree (created_at);


--
-- Name: idx_task_delegations_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_delegations_state ON public.task_delegations USING btree (state);


--
-- Name: idx_task_delegations_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_delegations_task ON public.task_delegations USING btree (task_id);


--
-- Name: idx_task_delegations_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_delegations_to ON public.task_delegations USING btree (to_user);


--
-- Name: idx_tasks_assigned_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_assigned_to ON public.tasks USING btree (assigned_to);


--
-- Name: idx_tasks_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_category ON public.tasks USING btree (category) WHERE (is_active = true);


--
-- Name: idx_tasks_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_created_by ON public.tasks USING btree (created_by);


--
-- Name: idx_tasks_due_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_due_date ON public.tasks USING btree (due_date) WHERE (is_active = true);


--
-- Name: idx_tasks_routing_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_routing_state ON public.tasks USING btree (routing_state);


--
-- Name: idx_verifications_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_state ON public.verifications USING btree (state);


--
-- Name: idx_verifications_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_task ON public.verifications USING btree (task_id);


--
-- Name: growth_scores_28d _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.growth_scores_28d AS
 WITH win AS (
         SELECT (now() - '28 days'::interval) AS start_ts
        ), comp AS (
         SELECT t.id AS task_id,
            t.title,
            t.category,
            t.priority,
            t.assigned_to,
            t.is_recurring,
            t.recurrence_pattern,
            t.due_date,
            count(tc.id) FILTER (WHERE (tc.completed_at >= ( SELECT win.start_ts
                   FROM win))) AS completions_28d,
            COALESCE(sum(tc.points) FILTER (WHERE ((tc.completed_at >= ( SELECT win.start_ts
                   FROM win)) AND (tc.points > 0))), (0)::bigint) AS pos_pts_28d,
            max(tc.completed_at) AS last_completed
           FROM (public.tasks t
             LEFT JOIN public.task_completions tc ON ((tc.task_id = t.id)))
          WHERE t.is_active
          GROUP BY t.id
        ), expected AS (
         SELECT c.task_id,
            c.title,
            c.category,
            c.priority,
            c.assigned_to,
            c.is_recurring,
            c.recurrence_pattern,
            c.due_date,
            c.completions_28d,
            c.pos_pts_28d,
            c.last_completed,
                CASE
                    WHEN (NOT c.is_recurring) THEN 1.0
                    WHEN ((c.recurrence_pattern)::text ~~* '%daily%'::text) THEN 28.0
                    WHEN ((c.recurrence_pattern)::text ~~* '%weekly%'::text) THEN 4.0
                    WHEN ((c.recurrence_pattern)::text ~~* '%month%'::text) THEN 1.0
                    ELSE 4.0
                END AS expected_28d
           FROM comp c
        )
 SELECT e.task_id,
    e.title,
    e.category,
    e.priority,
    e.assigned_to,
    e.completions_28d,
    e.expected_28d,
    e.pos_pts_28d,
    e.last_completed,
    GREATEST((e.expected_28d - (e.completions_28d)::numeric), (0)::numeric) AS missed_28d,
    round((((e.pos_pts_28d)::numeric - ((2)::numeric * GREATEST((e.expected_28d - (e.completions_28d)::numeric), (0)::numeric))) / NULLIF(e.expected_28d, (0)::numeric)), 2) AS growth_score
   FROM expected e;


--
-- Name: tasks update_tasks_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE ON public.tasks FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: agent_domains agent_domains_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_domains
    ADD CONSTRAINT agent_domains_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.users(id);


--
-- Name: agent_domains agent_domains_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_domains
    ADD CONSTRAINT agent_domains_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);


--
-- Name: notifications notifications_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: self_assessments self_assessments_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.self_assessments
    ADD CONSTRAINT self_assessments_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: tag_dependencies tag_dependencies_depends_on_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_dependencies
    ADD CONSTRAINT tag_dependencies_depends_on_tag_id_fkey FOREIGN KEY (depends_on_tag_id) REFERENCES public.tags(id);


--
-- Name: tag_dependencies tag_dependencies_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_dependencies
    ADD CONSTRAINT tag_dependencies_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);


--
-- Name: tags tags_parent_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_parent_tag_id_fkey FOREIGN KEY (parent_tag_id) REFERENCES public.tags(id);


--
-- Name: task_completions task_completions_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_completions
    ADD CONSTRAINT task_completions_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_delegations task_delegations_from_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_delegations
    ADD CONSTRAINT task_delegations_from_user_fkey FOREIGN KEY (from_user) REFERENCES public.users(id);


--
-- Name: task_delegations task_delegations_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_delegations
    ADD CONSTRAINT task_delegations_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: task_delegations task_delegations_to_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_delegations
    ADD CONSTRAINT task_delegations_to_user_fkey FOREIGN KEY (to_user) REFERENCES public.users(id);


--
-- Name: task_skill_requirements task_skill_requirements_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_skill_requirements
    ADD CONSTRAINT task_skill_requirements_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);


--
-- Name: task_skill_requirements task_skill_requirements_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_skill_requirements
    ADD CONSTRAINT task_skill_requirements_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: task_tags task_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_tags
    ADD CONSTRAINT task_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);


--
-- Name: task_tags task_tags_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_tags
    ADD CONSTRAINT task_tags_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: tasks tasks_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id);


--
-- Name: tasks tasks_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: verifications verifications_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verifications
    ADD CONSTRAINT verifications_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);


--
-- Name: verifications verifications_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verifications
    ADD CONSTRAINT verifications_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


