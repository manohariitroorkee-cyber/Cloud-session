-- Revision integrity (audit findings): frozen revisions are immutable, object and
-- relationship versions cannot overlap, and supporting indexes.
SET search_path = infra, public;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- 1. Two versions of the same object (or relationship) may not cover the same revision.
ALTER TABLE eng_object_version
    ADD CONSTRAINT eng_object_no_overlap
    EXCLUDE USING gist (object_id WITH =, int4range(rev_from, rev_to) WITH &&);

ALTER TABLE eng_relationship
    ADD CONSTRAINT eng_relationship_no_overlap
    EXCLUDE USING gist (source_id WITH =, target_id WITH =, type WITH =, int4range(rev_from, rev_to) WITH &&);

-- 2. A frozen revision is immutable.  Rows that are visible in a frozen revision
--    (rev_from <= frozen number < rev_to) may not be changed or deleted; the only
--    permitted change is closing an open row (setting rev_to) at a revision AFTER
--    every frozen revision it is visible in, which is how a new version supersedes it.
CREATE FUNCTION protect_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    last_frozen integer;
BEGIN
    SELECT max(number) INTO last_frozen
      FROM revision
     WHERE project_id = OLD.project_id AND frozen
       AND number >= OLD.rev_from AND (OLD.rev_to IS NULL OR number < OLD.rev_to);
    IF last_frozen IS NULL THEN
        -- the row was outside every frozen revision: an update may not move it into one
        IF TG_OP = 'UPDATE' AND EXISTS (
            SELECT 1 FROM revision
             WHERE project_id = NEW.project_id AND frozen
               AND number >= NEW.rev_from AND (NEW.rev_to IS NULL OR number < NEW.rev_to)) THEN
            RAISE EXCEPTION 'this change would make the row part of a frozen revision';
        END IF;
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'row % is part of frozen revision % and cannot be deleted', OLD, last_frozen;
    END IF;
    -- only allowed: closing an open row at a revision after the frozen one, nothing else changed
    IF OLD.rev_to IS NULL AND NEW.rev_to IS NOT NULL AND NEW.rev_to > last_frozen
       AND (to_jsonb(NEW) - 'rev_to') = (to_jsonb(OLD) - 'rev_to') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'row is part of frozen revision %; create a new version in an open revision instead', last_frozen;
END $$;

CREATE TRIGGER eng_object_frozen BEFORE UPDATE OR DELETE ON eng_object_version
    FOR EACH ROW EXECUTE FUNCTION protect_frozen();
CREATE TRIGGER eng_relationship_frozen BEFORE UPDATE OR DELETE ON eng_relationship
    FOR EACH ROW EXECUTE FUNCTION protect_frozen();

-- new rows may not be visible in any frozen revision (neither added to one nor reaching into one)
CREATE FUNCTION insert_into_open_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE f integer;
BEGIN
    SELECT min(number) INTO f FROM revision
     WHERE project_id = NEW.project_id AND frozen
       AND number >= NEW.rev_from AND (NEW.rev_to IS NULL OR number < NEW.rev_to);
    IF f IS NOT NULL THEN
        RAISE EXCEPTION 'the new row would be part of frozen revision %; add the change to a later open revision', f;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER eng_object_open_rev BEFORE INSERT ON eng_object_version
    FOR EACH ROW EXECUTE FUNCTION insert_into_open_revision();
CREATE TRIGGER eng_relationship_open_rev BEFORE INSERT ON eng_relationship
    FOR EACH ROW EXECUTE FUNCTION insert_into_open_revision();

-- a revision, once frozen, stays frozen and cannot be deleted or renumbered
CREATE FUNCTION keep_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.frozen THEN
            RAISE EXCEPTION 'revision % of project % is frozen and cannot be deleted', OLD.number, OLD.project_id;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.frozen AND (NOT NEW.frozen OR NEW.number <> OLD.number OR NEW.project_id <> OLD.project_id) THEN
        RAISE EXCEPTION 'revision % of project % is frozen and cannot be unfrozen or renumbered', OLD.number, OLD.project_id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER revision_keep_frozen BEFORE UPDATE OR DELETE ON revision
    FOR EACH ROW EXECUTE FUNCTION keep_frozen();

-- 3. Indexes and uniqueness
CREATE INDEX IF NOT EXISTS eng_object_geom_current_gix ON eng_object_version USING gist (geom) WHERE rev_to IS NULL;
CREATE INDEX IF NOT EXISTS check_result_object ON check_result (object_id);
CREATE UNIQUE INDEX IF NOT EXISTS rule_override_active_uq
    ON rule_override (project_id, parameter_id) WHERE superseded_at IS NULL;
