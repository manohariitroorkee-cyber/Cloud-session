# City Infrastructure Engineering Platform – Architecture

Status: foundation, sewer (+SWMM), water (+EPANET), storm drainage (hydraulic, +SWMM), road
alignment/curve design and electrical distribution (radial demand, loading, current, voltage drop) implemented on branch `platform/foundation-stage1`. Pavement thickness design and
structural (RCC) design are out of scope. See `IMPLEMENTATION_PLAN.md` for what is done and what is pending.

---

## 1. Current repository (as inspected)

| Part | What it is | Assessment |
|---|---|---|
| `src/`, `include/`, `run/`, `tests/`, `CMakeLists.txt` | **OWA-EPANET 2.3.6** hydraulic/water-quality solver in C (MIT licence), with its CLI `runepanet` and Boost unit tests | Upstream engine code. **Kept unchanged** and reused as the platform's EPANET engine (built as `libepanet2`). |
| `my-custom-app/` | C++ CLI `epanet-pressures` that links the engine and prints node pressures; `ARCHITECTURE.md` documents the engine internals | Useful reference and build pattern. Kept. |
| `web-src/` → `index.html` | Single-file, offline **EPANET network designer**: canvas drawing in screen coordinates, epanet-js (WebAssembly) in the browser, undo/redo, INP import/export, result tables and graphs; state in `localStorage` | Good UX ideas and a correct INP writer, but **not georeferenced, no database, no server, calculations in the browser**. It does not meet the platform architecture (engine in the backend, GIS model in PostGIS). Kept as a standalone quick-sketch tool; its UI patterns (tools, inspector, result dock) carry over to the new GIS frontend. |
| `.github/workflows/` | Upstream EPANET CI (Linux/macOS/Windows builds) | Kept. A separate `platform.yml` workflow is added for the platform. |

There was **no backend, database, GIS layer, user model, or SWMM integration** in the repository.

## 2. Target architecture

```
Browser (MapLibre GL, TypeScript)          ← basemap tiles from external providers (display only)
   │  REST/JSON + vector tiles (MVT)
   ▼
API (FastAPI, Python)                      ← auth, permissions, revisions, import/export, job submission
   │
   ├── Engineering model  (cityinfra.model)       one object model for all disciplines
   ├── Rules framework    (cityinfra.rules)       traceable, configurable design criteria
   ├── Discipline modules (cityinfra.engineering) network building, design checks, quantities
   │       sewer · water · drainage · roads · electrical · png · telecom
   ├── Engine adapters    (cityinfra.engines)     convert model ⇄ engine input/output
   │       swmm  → libswmm5   (EPA SWMM 5.2.4, built from USEPA source at a pinned tag)
   │       epanet → libepanet2 (EPANET 2.3, built from THIS repository)
   ├── Reports / drawings (cityinfra.reports, drawings)
   ▼
PostgreSQL + PostGIS                       ← the engineering database (geometry + attributes + history)
```

Rules that hold in every layer:

* **No calculations in the frontend.** The browser draws, edits and displays; every number comes from the API.
* **Basemap is not data.** Satellite/street imagery is only a backdrop. Engineering geometry is created, imported and stored in our own database, in the project's projected CRS (EPSG:32643 – UTM 43N for Delhi).
* **Engines are adapters.** SWMM and EPANET are called through `engines/*/adapter.py`; nothing else imports them. Their input files and reports are stored with every run so any result can be reproduced.
* **Calculation ≠ check ≠ approval.** A calculation run records method, engine, version and the full rule snapshot. Checks cite the parameter, document, clause and verification state. Approval is a separate record made by a named person; software never sets an object to "approved".
* **Pending is explicit.** A discipline or engine that is not implemented reports `pending`; it never returns placeholder numbers.

### Repository layout (adapted to the existing EPANET repo)

```
backend/                 Python package `cityinfra` + tests
  cityinfra/model/       common engineering model
  cityinfra/gis/         geometry measurement, GeoJSON I/O
  cityinfra/rules/       rule framework + rulesets/*.yaml
  cityinfra/engineering/ sewer/ water/ drainage/ roads/ electrical/ png/ telecom/
  cityinfra/engines/     swmm/ epanet/ (adapters)
  cityinfra/reports/     design-check reports
  tests/
database/migrations/     numbered PostGIS SQL migrations + verify_schema.sql
engines/build_engines.sh builds libepanet2 (this repo) + libswmm5 (USEPA) into engines/lib/
frontend/                (stage 2) MapLibre GIS client
docs/platform/           this document, implementation plan
src/ include/ run/ …     upstream EPANET engine – unchanged
web-src/ index.html      existing standalone designer – unchanged
```

The upstream EPANET tree stays at the root so upstream merges and its CI keep working.

## 3. Technology and dependencies

| Area | Choice | Licence | Why |
|---|---|---|---|
| Language (backend/engineering) | Python 3.11+ | PSF | Best ecosystem for SWMM/EPANET/GIS/numerics; readable for engineers |
| API | FastAPI + Pydantic v2, Uvicorn | MIT/BSD | Typed, OpenAPI docs generated automatically |
| Database | PostgreSQL 15+ with PostGIS 3.3+ | PostgreSQL / GPL-2 (server-side) | Spatial indexing, ST_* functions, MVT tile generation |
| DB access | psycopg 3; plain SQL migrations (wrappable in Alembic later) | LGPL-3 | Transparent SQL, no ORM lock-in |
| CRS / formats | pyproj, GDAL/OGR via pyogrio (SHP, KML/KMZ, GeoPackage, GeoJSON) | MIT | Standard open GIS stack |
| CAD | ezdxf (DXF read/write) | MIT | DXF import and drawing export |
| DWG | Convert to DXF with ODA File Converter (free, proprietary) or LibreDWG (GPL-3) as an external step | — | No open, permissive DWG reader exists; kept outside the codebase |
| Sewer/drainage engine | EPA SWMM 5.2.4 (C library, ctypes) | US Government work, public domain (USEPA disclaimer applies) | Industry standard; not re-implemented |
| Water engine | EPANET 2.3 from this repository (ctypes) | MIT | Already the repository's code |
| Electrical (later) | pandapower | BSD-3 | Load flow, voltage drop, short circuit |
| Gas (later) | pandapipes | BSD-3 | Gas network pressure/flow |
| Frontend | TypeScript, Vite, MapLibre GL JS, Terra Draw (editing/snapping) | BSD/MIT | Open alternative to Google/Mapbox SDKs; no lock-in |
| Reports | Markdown/HTML → PDF (WeasyPrint) ; drawings via ezdxf | BSD | Editable and printable |
| Tests | unittest (pytest-compatible), GitHub Actions with a PostGIS service container | — | Runs on every push |

Rules sets are YAML files under version control; per-project overrides live in the database with a mandatory reason and author.

## 4. Database / GIS model

Full DDL: `database/migrations/0001_core.sql`.

* **project** – code, name, `crs_epsg` (geographic CRSs rejected by constraint), boundary.
* **revision** – `(project_id, number)`, label, frozen flag, `based_on` (for roll-forward of an older revision).
* **eng_object_version** – one row per *version* of an engineering object: `object_id`, `kind`, `discipline`, `name`, `status`, `geom` (SRID checked against the project by trigger, validity checked), `z_min`/`z_max` (levels for 3-D clash queries), `attributes jsonb`, `rev_from`/`rev_to`. The view `eng_object` is the current state. State at revision *N*: `rev_from ≤ N < coalesce(rev_to, ∞)`. Comparison between revisions is a diff of these row sets; rollback creates a new revision copying an older state (history is never deleted).
* **eng_relationship** – typed, versioned links between objects: `upstream_node`, `downstream_node`, `serves`, `located_in`, `crosses`, `depends_on_level`, `feeds`. These carry topology and the change-impact graph (road → drains/sewers/water → crossings).
* **design_ruleset / project_ruleset / rule_override** – rule sets, their order per discipline, and justified project overrides.
* **calc_run / calc_result / check_result** – each run with method, engine, engine version, full rule snapshot, engine input and report; per-object results; per-check results citing parameter, source and verification state.
* **approval** – human decisions (`checked`, `approved`, `returned`, `rejected`) against a run, with name and capacity.
* **quantity_item / rate_schedule / rate** – quantities generated from objects (with derivation text) kept separate from rates; BOQ is a join.
* **app_user / project_member** – per-project rights: view, edit, calculate, approve, manage; platform admin separately.
* **audit_log**.

Performance: GiST index on geometry, partial indexes on current rows, GIN on attributes. The map loads **vector tiles for the current viewport only** (`ST_AsMVT`), never the whole project; object detail is fetched on selection. Engine runs are executed by worker processes off a Postgres job table (`SELECT … FOR UPDATE SKIP LOCKED`), so the API never blocks on a simulation and SWMM's global state is isolated per process.

Object kinds and their geometry: `cityinfra/model/core.py` (`KIND_SPEC`) — development boundary, plot, parcel, terrain point, road, road alignment, road junction, manhole, sewer pipe/outfall, catchment, drain node/drain/outfall, water junction/pipe, reservoir, tank, pump, valve, substation, transformer, electrical cable, pole, PNG source/regulator/node/pipeline, telecom chamber/duct, fibre cable, network cabinet, utility crossing.

## 5. Engineering-engine integration strategy

| Engine | Source | Build | Called through | Isolation |
|---|---|---|---|---|
| EPANET 2.3 | this repository (`src/`) | `engines/build_engines.sh` → `engines/lib/libepanet2.so` | `cityinfra.engines.epanet.adapter` (project-handle API `epanet2_2.h`) | Re-entrant API; one project handle per run |
| EPA SWMM 5.2.4 | `github.com/USEPA/Stormwater-Management-Model`, tag `v5.2.4`, fetched at build time (not copied into this repo) | same script → `engines/lib/libswmm5.so` | `cityinfra.engines.swmm.adapter` (C API `swmm5.h`) | SWMM uses global state → process lock now; worker processes in production |

Each adapter: (1) validates the network, (2) writes the engine's native input file from the model, (3) runs the engine in a temporary directory, (4) reads results through the engine API, (5) maps them back to object IDs, (6) returns an `EngineRun` record with input text, report text, version, status and messages. If a library is absent the adapter raises `EngineUnavailable`, which the API reports as *pending* – never as a result. Library paths can be overridden with `CITYINFRA_SWMM_LIB` / `CITYINFRA_EPANET_LIB` (e.g. to use a Windows DLL).

Sewer design uses two complementary methods and reports both:

1. **Design sheet** (in-house, standard): cumulative population → per-capita sewage → peak factor → infiltration → Manning partial-flow hydraulics → checks against the rule set → proposed alternatives.
2. **Network simulation** (EPA SWMM, dynamic wave): constant design peak inflows to steady state → flows, depths, velocities, HGL, surcharge and flooding including backwater effects.

Verification done in stage 1 (automated tests): SWMM steady flows reproduce design-sheet flows within 1 %; an undersized outlet produces surcharge and flooding that propagate upstream; EPANET mass balance closes and pipe head loss matches a hand Hazen–Williams calculation within 1 %.
