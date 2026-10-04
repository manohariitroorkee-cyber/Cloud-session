# cityinfra – backend core

Engineering model, design rules, discipline modules and engine adapters for the
city infrastructure engineering platform. Architecture: `../docs/platform/ARCHITECTURE.md`.

## Set up (Linux/macOS/WSL; Windows via WSL is simplest)

```bash
engines/build_engines.sh                  # from repo root: builds libepanet2 (this repo) + libswmm5 (USEPA)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -t .   # 135 tests; engine tests skip if libraries are absent
```

## The simple app (for non-specialists)

```bash
python -m cityinfra.app            # opens http://127.0.0.1:8765 – or double-click start-app.bat / start-app.sh
python ui_audit/check_app.py out/  # browser walk-through of every module (needs: pip install playwright)
```

Draw on a sheet, fill in a few plain fields (suggested values are marked), press *Check my design*,
and read the results as traffic lights with advice. How to use it: `../docs/platform/USER_GUIDE.md`.
Code: `cityinfra/app/` – `api.py` (checks → plain results), `plain.py` (wording and advice for every
check), `server.py` (standard-library HTTP server on 127.0.0.1), `static/` (page, no build step).

## Try it from the command line

```bash
python -m cityinfra.cli sewer --sample -o sewer_report.md   # synthetic network: design sheet + SWMM
python -m cityinfra.cli water --sample                       # synthetic network: EPANET + pressure checks
python -m cityinfra.cli drainage --sample                    # synthetic IDF + catchments: Rational sheet + SWMM storm
python -m cityinfra.cli road --sample                        # alignment, curves, long-section, utility level impacts
python -m cityinfra.cli junction --sample                    # intersections and a roundabout
python -m cityinfra.cli electrical --sample                  # demand, transformer loading, cable current and voltage drop
python -m cityinfra.cli sewer my_network.geojson --epsg 32643
```

GeoJSON input: one Feature per object with `properties.kind` (e.g. `manhole`, `sewer_pipe`,
`sewer_outfall`), `name`, attributes (`ground_level`, `population`, `diameter_mm`, `material`,
`us_invert`, `ds_invert`, …) and, for pipes, `from`/`to` manhole names. Coordinates must be in the
project's projected CRS (metres).

All output is a calculation, not a certified design. Design criteria marked
`requires_verification` must be checked against the source documents before use.
