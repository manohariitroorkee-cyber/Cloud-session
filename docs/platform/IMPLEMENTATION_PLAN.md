# Implementation plan and status

Legend: **done** = implemented and tested · **partial** = foundation in place · **pending** = not implemented (the platform must say so, not show results).

## Stage status

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | Inspect repository, current architecture | done | `ARCHITECTURE.md` §1 |
| 2 | Target architecture, technology list | done | `ARCHITECTURE.md` §2–3 |
| 3 | Common engineering model (in-memory) | done | `cityinfra/model/core.py` – all object kinds, statuses, relationships, change-impact traversal |
| 4 | PostGIS schema | partial | `0001_core.sql` written; non-spatial DDL syntax-checked locally; full PostGIS verification runs in CI (`verify_schema.sql`). Repository/persistence code: pending (stage 2) |
| 5 | GIS geometry & GeoJSON import/export | partial | planar measurement in projected CRS, GeoJSON round-trip with topology. DXF/SHP/KML/KMZ import: pending (needs GDAL/ezdxf in API layer) |
| 6 | Design-rules framework | done | YAML rule sets with source, clause, verification state; project overrides with reason/author |
| 7 | Sewer module (design sheet, checks, alternatives) | done | Manning partial flow, population accumulation, peak factor, infiltration, d/D, velocities, min diameter, cover, invert continuity, manhole spacing; alternatives proposed only |
| 8 | SWMM adapter | done | INP generation, real SWMM 5.2.4 run, flows/depths/velocities/HGL/surcharge/flooding, continuity error |
| 9 | Water / EPANET adapter | done | GIS network → INP → this repo's EPANET 2.3.6 → pressures/heads/flows/velocities/head loss; pressure checks |
| 10 | Sewer report | done | Markdown report: banner, method, criteria + verification state, sheet, failed checks, alternatives, SWMM results, blank approval block |
| — | HTTP API (FastAPI), auth, permissions | pending | stage 2 |
| — | GIS frontend (MapLibre, drawing, snapping, measurement, undo/redo, layers, results on map) | pending | stage 2 |
| — | Revisions: compare / rollback services | pending | schema ready; services stage 2 |
| 11 | Storm-water drainage – hydraulic design | done | Catchments (composite C, Kirpich/inlet time), project IDF (power or table form, no default), Rational-method sheet with iterated time of concentration, circular/rectangular/trapezoidal/box sections, capacity, d/D, freeboard, velocities, return-period check, size alternatives; SWMM runoff + dynamic-wave routing with alternating-block design storm, flooding and surcharge |
| 12 | Roads – alignment and curve design | done | Horizontal: circular curves + clothoid transitions, chainage, station/offset; checks R_min, transition length (centrifugal-acceleration and superelevation run-off). Vertical: grades, parabolic curves; checks max/min grade, curve length for SSD (crest and headlight sag). TIN ground, long-section, cross-section surface geometry, utilities whose cover level must follow the road (and change-impact links) |
| — | Electrical (hierarchy, load, voltage drop, cable sizing) | pending | awaiting scope confirmation |
| — | PNG / gas | pending | stage 5 – candidate engine pandapipes |
| — | Telecom / fibre (ducts, chambers, capacity) | pending | stage 5 |
| — | Quantities / BOQ / drawings (plan, L-section, schedules, DXF/PDF) | pending | schema for quantities & rates ready |
| — | Utility corridor & crossing clash detection | pending | uses `z_min/z_max` + PostGIS 3-D queries |

## Out of scope (by decision of 4 Oct 2026)

* Pavement thickness design (IRC:37) and pavement layers.
* Structural (RCC) design of drains, culverts, chambers, manholes and any other structure.
* Road earthwork and quantities (removed from the roads module with the above; can be reinstated on instruction).

## Next stage: make it usable on a map

1. `backend/cityinfra/db/` – psycopg repository: load/save `Project` ⇄ `eng_object_version`, revisions (create, freeze, diff, roll forward).
2. FastAPI app: projects, objects (CRUD with SRID/kind validation), relationships, import (GeoJSON, DXF, SHP, KML/KMZ), vector tiles, sewer-design and SWMM jobs, EPANET jobs, results, reports; users and per-project rights.
3. `frontend/`: MapLibre map with switchable basemaps, project boundary, layers per discipline, draw/edit manholes and pipes with snapping, measurement (distance, angle, coordinates), attribute inspector, undo/redo, run sewer check, colour pipes by check result, L-section view.
4. CI: PostGIS service container; schema verification; API tests.

## Items requiring the engineer's confirmation

* Every value in `cpheeo_sewerage_2013.yaml`, `cpheeo_water_supply.yaml`, `cpheeo_storm_water_2019.yaml` and `irc_geometric_design.yaml` is `requires_verification`. The storm-water and IRC values came from secondary summaries and textbook statements of the codes, and several clause numbers are unconfirmed.
* Drainage needs a project IDF relationship (IMD data or hydrology report); none is shipped. The sample IDF is synthetic. Peak-factor table (Table 3.2), Manning *n* for RCC/stoneware, manhole spacing table and the residual-pressure table were **not** seen in a primary source during development.
* `dda_project_defaults.yaml` holds project decisions (water supply lpcd, town population, available diameters) – set per project.
* Which DDA-specific requirements should be added as a separate rule set.
* Basemap provider(s) and their licence terms for official use.
