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

-- revision integrity (0003): frozen revisions are immutable, versions cannot overlap
INSERT INTO revision (project_id, number, label) VALUES ('00000000-0000-0000-0000-0000000000a1', 1, 'R1');
UPDATE revision SET frozen = true WHERE project_id = '00000000-0000-0000-0000-0000000000a1' AND number = 0;
DO $$ BEGIN
    UPDATE eng_object_version SET name = 'X' WHERE name = 'MH1';
    RAISE EXCEPTION 'frozen edit allowed';
EXCEPTION WHEN raise_exception THEN IF SQLERRM = 'frozen edit allowed' THEN RAISE; END IF;
END $$;
DO $$ BEGIN
    DELETE FROM eng_object_version WHERE name = 'MH1';
    RAISE EXCEPTION 'frozen delete allowed';
EXCEPTION WHEN raise_exception THEN IF SQLERRM = 'frozen delete allowed' THEN RAISE; END IF;
END $$;
UPDATE eng_object_version SET rev_to = 1 WHERE name = 'MH1';                      -- supersede in open R1
INSERT INTO eng_object_version (object_id, project_id, rev_from, kind, discipline, name, geom)
SELECT object_id, project_id, 1, kind, discipline, 'MH1-v2', ST_Translate(geom, 1, 0) FROM eng_object_version WHERE name = 'MH1';
DO $$ BEGIN
    INSERT INTO eng_object_version (object_id, project_id, rev_from, rev_to, kind, discipline, name, geom)
    SELECT object_id, project_id, 1, 2, kind, discipline, 'old', geom FROM eng_object_version WHERE name = 'MH1-v2';
    RAISE EXCEPTION 'overlap allowed';
EXCEPTION WHEN exclusion_violation THEN NULL;
END $$;
DO $$ BEGIN
    UPDATE revision SET frozen = false WHERE number = 0 AND project_id = '00000000-0000-0000-0000-0000000000a1';
    RAISE EXCEPTION 'unfreeze allowed';
EXCEPTION WHEN raise_exception THEN IF SQLERRM = 'unfreeze allowed' THEN RAISE; END IF;
END $$;
ROLLBACK;
\echo 'schema verification passed'
