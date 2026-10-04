-- City infrastructure engineering platform – core schema (PostgreSQL 15+ / PostGIS 3.3+)
--
-- Principles
--  * One common engineering model: every object of every discipline is a row
--    in eng_object_version; discipline data lives in `attributes` (jsonb),
--    validated by the application against per-kind schemas.
--  * Geometry is stored in the project's projected metric CRS (e.g. EPSG:32643).
--    The web map receives vector tiles transformed to EPSG:3857 on the fly.
--    Basemap imagery is never stored or used as engineering data.
--  * Revisions: rows are versioned by revision number (rev_from / rev_to), so any
--    revision can be reconstructed, compared and rolled forward from.
--  * Calculation, checks and approval are separate records.  An approval is a
--    human decision against a specific calculation run; software never approves.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;          -- gen_random_uuid()

CREATE SCHEMA IF NOT EXISTS infra;
SET search_path = infra, public;

-- ---------------------------------------------------------------- users & rights
CREATE TABLE app_user (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text NOT NULL UNIQUE,
    full_name   text NOT NULL,
    designation text,
    is_admin    boolean NOT NULL DEFAULT false,      -- platform administration only
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Rights are per project. They are additive flags rather than one role so that,
-- e.g., a reviewer can approve without being able to edit.
CREATE TABLE project_member (
    project_id     uuid NOT NULL,
    user_id        uuid NOT NULL REFERENCES app_user(id),
    can_view       boolean NOT NULL DEFAULT true,
    can_edit       boolean NOT NULL DEFAULT false,   -- create/modify engineering objects
    can_calculate  boolean NOT NULL DEFAULT false,   -- run engines and design checks
    can_approve    boolean NOT NULL DEFAULT false,   -- record approval decisions
    can_manage     boolean NOT NULL DEFAULT false,   -- members, rule sets, revisions
    PRIMARY KEY (project_id, user_id)
);

-- ---------------------------------------------------------------- project & revisions
CREATE TABLE project (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code        text NOT NULL UNIQUE,
    name        text NOT NULL,
    crs_epsg    integer NOT NULL CHECK (crs_epsg NOT IN (4326, 4269, 4258)),  -- projected CRS only
    boundary    geometry(MultiPolygon),
    description text,
    created_by  uuid REFERENCES app_user(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE project_member ADD FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;

CREATE TABLE revision (
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    number      integer NOT NULL CHECK (number >= 0),
    label       text NOT NULL,                       -- e.g. "R0 – tender design"
    note        text,
    frozen      boolean NOT NULL DEFAULT false,      -- a frozen revision is immutable
    based_on    integer,                             -- for rollback: the revision copied from
    created_by  uuid REFERENCES app_user(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, number)
);

-- ---------------------------------------------------------------- engineering objects
CREATE TYPE discipline AS ENUM ('common','roads','sewer','drainage','water','electrical','png','telecom');
CREATE TYPE object_status AS ENUM ('existing','proposed','calculated','checked','approved','superseded');

-- One row per version of an object.  Current state: rev_to IS NULL.
-- State at revision N: rev_from <= N AND (rev_to IS NULL OR rev_to > N).
CREATE TABLE eng_object_version (
    version_id  bigserial PRIMARY KEY,
    object_id   uuid NOT NULL,
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    rev_from    integer NOT NULL,
    rev_to      integer,
    kind        text NOT NULL,                        -- ObjectKind value (application enum)
    discipline  discipline NOT NULL,
    name        text,
    status      object_status NOT NULL DEFAULT 'proposed',
    geom        geometry NOT NULL,                    -- SRID = project.crs_epsg (trigger-checked)
    z_min       double precision,                     -- lowest level (e.g. invert), for 3-D clash queries
    z_max       double precision,                     -- highest level (e.g. ground / crown)
    attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
    changed_by  uuid REFERENCES app_user(id),
    changed_at  timestamptz NOT NULL DEFAULT now(),
    change_note text,
    CHECK (rev_to IS NULL OR rev_to > rev_from),
    FOREIGN KEY (project_id, rev_from) REFERENCES revision(project_id, number)
);
CREATE UNIQUE INDEX eng_object_current_uq ON eng_object_version (object_id) WHERE rev_to IS NULL;
CREATE INDEX eng_object_geom_gix   ON eng_object_version USING gist (geom);
CREATE INDEX eng_object_proj_kind  ON eng_object_version (project_id, kind) WHERE rev_to IS NULL;
CREATE INDEX eng_object_hist       ON eng_object_version (object_id, rev_from);
CREATE INDEX eng_object_attr_gin   ON eng_object_version USING gin (attributes jsonb_path_ops);

CREATE FUNCTION check_object_srid() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE want integer;
BEGIN
    SELECT crs_epsg INTO want FROM project WHERE id = NEW.project_id;
    IF ST_SRID(NEW.geom) <> want THEN
        RAISE EXCEPTION 'geometry SRID % does not match project CRS EPSG:%', ST_SRID(NEW.geom), want;
    END IF;
    IF NOT ST_IsValid(NEW.geom) THEN
        RAISE EXCEPTION 'invalid geometry for object % (%): %', NEW.object_id, NEW.kind, ST_IsValidReason(NEW.geom);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER eng_object_srid BEFORE INSERT OR UPDATE OF geom ON eng_object_version
    FOR EACH ROW EXECUTE FUNCTION check_object_srid();

CREATE TYPE relation_type AS ENUM
    ('upstream_node','downstream_node','serves','located_in','crosses','depends_on_level','feeds');

CREATE TABLE eng_relationship (
    id          bigserial PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    source_id   uuid NOT NULL,                        -- object_id
    target_id   uuid NOT NULL,                        -- object_id
    type        relation_type NOT NULL,
    attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
    rev_from    integer NOT NULL,
    rev_to      integer,
    CHECK (source_id <> target_id),
    CHECK (rev_to IS NULL OR rev_to > rev_from)
);
CREATE INDEX eng_rel_source ON eng_relationship (source_id) WHERE rev_to IS NULL;
CREATE INDEX eng_rel_target ON eng_relationship (target_id) WHERE rev_to IS NULL;

-- Current state, for ordinary queries and tile generation.
CREATE VIEW eng_object AS
    SELECT * FROM eng_object_version WHERE rev_to IS NULL;

-- ---------------------------------------------------------------- design rules
CREATE TABLE design_ruleset (
    id              text PRIMARY KEY,                 -- e.g. cpheeo_sewerage_2013
    title           text NOT NULL,
    source_document text NOT NULL,
    content         jsonb NOT NULL,                   -- parameters with value/unit/source/verification
    loaded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_ruleset (
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    discipline  discipline NOT NULL,
    layer_order integer NOT NULL,                     -- later layers override earlier
    ruleset_id  text NOT NULL REFERENCES design_ruleset(id),
    PRIMARY KEY (project_id, discipline, layer_order)
);

CREATE TABLE rule_override (
    id           bigserial PRIMARY KEY,
    project_id   uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    parameter_id text NOT NULL,
    value        jsonb NOT NULL,
    unit         text,
    reason       text NOT NULL,                       -- mandatory justification
    decided_by   uuid NOT NULL REFERENCES app_user(id),
    decided_at   timestamptz NOT NULL DEFAULT now(),
    superseded_at timestamptz
);

-- ---------------------------------------------------------------- calculations
CREATE TYPE run_status AS ENUM ('queued','running','ok','warning','error','pending_engine');

CREATE TABLE calc_run (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    revision_number  integer NOT NULL,
    discipline       discipline NOT NULL,
    method           text NOT NULL,                   -- e.g. "Manning design-sheet" / "SWMM dynamic wave"
    engine           text,                            -- "EPA SWMM", "EPANET", NULL for in-house method
    engine_version   text,
    status           run_status NOT NULL DEFAULT 'queued',
    rules_snapshot   jsonb NOT NULL,                  -- every parameter used, with source & verification
    input_text       text,                            -- engine input file, for reproduction
    report_text      text,
    messages         jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_by       uuid REFERENCES app_user(id),
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    FOREIGN KEY (project_id, revision_number) REFERENCES revision(project_id, number)
);

CREATE TABLE calc_result (
    run_id     uuid NOT NULL REFERENCES calc_run(id) ON DELETE CASCADE,
    object_id  uuid NOT NULL,
    result     jsonb NOT NULL,                        -- e.g. {"design_flow_lps":..,"depth_ratio":..}
    PRIMARY KEY (run_id, object_id)
);

CREATE TYPE check_status AS ENUM ('pass','fail','warning','not_evaluated');

CREATE TABLE check_result (
    id            bigserial PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES calc_run(id) ON DELETE CASCADE,
    object_id     uuid NOT NULL,
    check_name    text NOT NULL,
    status        check_status NOT NULL,
    actual        double precision,
    limit_value   double precision,
    unit          text,
    parameter_id  text,
    source        text,                               -- document + clause cited
    verification  text,                               -- verification state of that parameter
    message       text NOT NULL
);
CREATE INDEX check_result_run ON check_result (run_id, status);

-- Human review/approval of a calculation run. Never written by an engine.
CREATE TYPE approval_decision AS ENUM ('checked','approved','returned','rejected');

CREATE TABLE approval (
    id             bigserial PRIMARY KEY,
    run_id         uuid NOT NULL REFERENCES calc_run(id),
    decision       approval_decision NOT NULL,
    decided_by     uuid NOT NULL REFERENCES app_user(id),
    capacity       text NOT NULL,                     -- designation/authority under which decided
    remarks        text,
    decided_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- quantities & rates
-- Quantities come from objects; rates are kept separately and joined for BOQ.
CREATE TABLE quantity_item (
    id            bigserial PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES calc_run(id) ON DELETE CASCADE,
    object_id     uuid NOT NULL,
    item_code     text NOT NULL,                      -- links to rate.item_code (e.g. DSR item)
    description   text NOT NULL,
    unit          text NOT NULL,
    quantity      double precision NOT NULL,
    derivation    text NOT NULL                       -- how the quantity was computed
);

CREATE TABLE rate_schedule (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,                        -- e.g. "DSR 2023" / "DDA market rates 2026"
    effective   date,
    source      text
);

CREATE TABLE rate (
    schedule_id bigint NOT NULL REFERENCES rate_schedule(id) ON DELETE CASCADE,
    item_code   text NOT NULL,
    description text NOT NULL,
    unit        text NOT NULL,
    rate        numeric(14,2) NOT NULL,
    PRIMARY KEY (schedule_id, item_code)
);

-- ---------------------------------------------------------------- audit
CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    project_id  uuid,
    user_id     uuid,
    action      text NOT NULL,
    detail      jsonb,
    at          timestamptz NOT NULL DEFAULT now()
);
