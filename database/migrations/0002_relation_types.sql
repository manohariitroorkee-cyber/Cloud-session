-- Stage 2 modules: catchment → inlet relationship.
SET search_path = infra, public;
ALTER TYPE relation_type ADD VALUE IF NOT EXISTS 'drains_to';
