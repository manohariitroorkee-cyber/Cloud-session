-- Schema verification: run after 0001_core.sql against a PostGIS database.
-- Exits non-zero (ON_ERROR_STOP) if any expectation fails.
\set ON_ERROR_STOP on
SET search_path = infra, public;

BEGIN;
INSERT INTO app_user (id, email, full_name) VALUES ('00000000-0000-0000-0000-000000000001', 'test@example.org', 'Test');
INSERT INTO project (id, code, name, crs_epsg) VALUES ('00000000-0000-0000-0000-0000000000a1', 'T1', 'Test', 32643);
INSERT INTO revision (project_id, number, label) VALUES ('00000000-0000-0000-0000-0000000000a1', 0, 'R0');

-- valid manhole in the project CRS
INSERT INTO eng_object_version (object_id, project_id, rev_from, kind, discipline, name, geom)
VALUES (gen_random_uuid(), '00000000-0000-0000-0000-0000000000a1', 0, 'manhole', 'sewer', 'MH1',
        ST_SetSRID(ST_MakePoint(704000, 3193000), 32643));

-- wrong SRID must be rejected
DO $$ BEGIN
    INSERT INTO eng_object_version (object_id, project_id, rev_from, kind, discipline, geom)
    VALUES (gen_random_uuid(), '00000000-0000-0000-0000-0000000000a1', 0, 'manhole', 'sewer',
            ST_SetSRID(ST_MakePoint(77.1, 28.85), 4326));
    RAISE EXCEPTION 'SRID check did not fire';
EXCEPTION WHEN raise_exception THEN
    IF SQLERRM LIKE 'SRID check did not fire' THEN RAISE; END IF;
END $$;

-- geographic CRS must be rejected for a project
DO $$ BEGIN
    INSERT INTO project (code, name, crs_epsg) VALUES ('T2', 'bad', 4326);
    RAISE EXCEPTION 'CRS check did not fire';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

-- spatial query works and uses metres
DO $$ DECLARE d double precision; BEGIN
    SELECT ST_Distance(geom, ST_SetSRID(ST_MakePoint(704030, 3193040), 32643)) INTO d FROM eng_object WHERE name = 'MH1';
    IF abs(d - 50) > 1e-6 THEN RAISE EXCEPTION 'distance % <> 50 m', d; END IF;
END $$;
ROLLBACK;
\echo 'schema verification passed'
