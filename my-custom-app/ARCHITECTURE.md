# EPANET 2.3 architecture notes

These notes cover how the EPANET 2.3 code in this repository is built, and how a
program (the stock `runepanet` CLI, or this folder's `epanet-pressures`) reaches
the hydraulic solver. Line numbers refer to the imported source and will move
if upstream changes.

## 1. Build layout (CMake)

```
CMakeLists.txt                (root, project EPANET, requires CMake 3.8+)
├── add_subdirectory(run)          → target runepanet   (executable, run/main.c)
├── add_subdirectory(src/outfile)  → target epanet-output (reads binary .out files)
├── add_library(epanet2 …)         → the engine: every src/*.c and src/util/*.c
└── [BUILD_TESTS=ON] tests/, tests/outfile, tests/util (needs Boost)
```

| Item | What it does |
|---|---|
| `BUILD_SHARED_LIBS` (default **ON**) | `epanet2` is built as `libepanet2.so` / `epanet2.dll`. Set OFF for a static library. |
| `BUILD_TESTS` (default OFF) | Adds the Boost unit tests. |
| `BUILD_COVERAGE` (default OFF) | Coverage build, using `cmake/CodeCoverage.cmake`. |
| `file(GLOB … src/*.c src/util/*.c)` | The engine has no hand-maintained source list; any `.c` file placed in `src/` is compiled into the library. |
| `target_include_directories(epanet2 PUBLIC include)` | Anything that links `epanet2` automatically gets `include/` (the public headers). This is what makes the library easy to embed. |
| Win32 + MSVC branch | Adds `include/epanet2.def` so 32-bit Windows exports undecorated `__stdcall` names (for VB/Delphi callers). |
| Output folders | Executables go to `<build>/bin`, libraries to `<build>/lib`. |
| `install(...)` | Installs `epanet2`, `runepanet` and the three public headers. |

`run/CMakeLists.txt` is just a consumer of the library:
`add_executable(runepanet main.c)` + `target_link_libraries(runepanet epanet2 m)`.

### Public headers (`include/`)

| Header | API style |
|---|---|
| `epanet2.h` | **Legacy 2.1-style API**: `ENopen`, `ENsolveH`, … operate on one hidden global project. Not thread-safe. |
| `epanet2_2.h` | **Project-handle API**: `EN_createproject`, `EN_open(ph, …)`, … Every call takes an `EN_Project`, so several networks can be open at once. Wrapped in `extern "C"`, so it can be included directly from C++. |
| `epanet2_enums.h` | Shared constants (`EN_PRESSURE`, `EN_NODECOUNT`, `EN_PSI`, …), included by both. |
| `epanet2.bas/.cs/.pas/.vb` | Declarations for VB, C#, Delphi and VB.NET callers of the same DLL. |

## 2. How `run/main.c` reaches the engine

`runepanet` is a thin shell: it parses the arguments, prints the version and hands
the whole run to one library call.

```
run/main.c  main()
  ENgetversion()                         print "Running EPANET Version 2.3.x"
  ENepanet(inp, rpt, out, writeConsole)  ← one call does everything
      │  src/epanet2.c  (legacy layer)
      ▼
  EN_createproject / EN_runproject(ph, …) / EN_deleteproject
      │  src/epanet.c  (project-handle API)
      ▼
  EN_runproject
    ├─ EN_open        → openproject()                      src/project.c
    │                     openfiles()    open .inp, .rpt (blank → stdout), scratch files
    │                     netsize()      1st pass: count objects        src/input2.c
    │                     allocdata()    allocate arrays                src/project.c
    │                     getdata()      2nd pass: parse all sections   src/input1.c, input2.c, input3.c
    ├─ EN_solveH      → openH / initH / loop{ runH ; nextH } / closeH
    │                     openhyd()      build the sparse matrix        src/hydraul.c, smatrix.c
    │                     runhyd()       demands() + controls() + hydsolve()
    │                                      hydsolve(): gradient-method Newton iterations   src/hydsolver.c
    │                                      head-loss / pump / valve coefficients           src/hydcoeffs.c, hydstatus.c
    │                     nexthyd()      save results, advance to next event time
    ├─ EN_solveQ      → water quality                            src/quality.c, qualroute.c, qualreact.c
    ├─ EN_report      → formatted .rpt                           src/report.c, output.c
    └─ EN_close
```

The legacy functions in `src/epanet2.c` are one-line wrappers over the
project-handle functions, for example `ENsolveH() { return EN_solveH(_defaultProject); }`,
using the single global `Project __defaultProject`.

The `writeConsole` callback passed to `ENepanet` is stored as `p->viewprog` and
receives progress strings (for example "Computing hydraulics at hour 5").

### Where the main pieces of engine code live

| Area | Files |
|---|---|
| Public API | `epanet.c` (EN_ functions), `epanet2.c` (legacy EN wrappers) |
| Project lifecycle, files, memory | `project.c`, `util/filemanager.c`, `mempool.c`, `hash.c` |
| Input parsing | `input1.c` (defaults and flow), `input2.c` (sizing and section dispatch), `input3.c` (section parsers), `inpfile.c` (writing .inp) |
| Hydraulics | `hydraul.c` (time loop, demands, tanks), `hydsolver.c` (Newton/GGA solver), `hydcoeffs.c`, `hydstatus.c`, `smatrix.c` + `genmmd.c` (sparse matrix ordering), `leakage.c`, `flowbalance.c` |
| Controls | `rules.c` (rule-based controls); simple controls live in `hydraul.c` |
| Water quality | `quality.c`, `qualroute.c`, `qualreact.c` |
| Output | `output.c` (binary results), `report.c` (text report), `src/outfile/` (separate reader library) |
| Shared internals | `types.h` (the `Project` struct), `funcs.h` (internal prototypes), `text.h`, `errors.dat` |

## 3. How `epanet-pressures` uses it

Where `runepanet` calls `ENepanet` and lets the engine do the whole run,
`epanet-pressures` uses the step-by-step functions from `epanet2_2.h`, so it can
read results between time steps:

```
EN_createproject(&ph)
EN_open(ph, inp, rpt, "")                 parse network (rpt defaults to the null device)
EN_getcount(EN_NODECOUNT / EN_LINKCOUNT / EN_TANKCOUNT)
EN_getoption(EN_PRESS_UNITS)              psi / m / kPa / bar / ft, from the .inp file
EN_getnodeid / EN_getnodetype             for every node, 1..N
EN_openH ; EN_initH(EN_NOSAVE)
do {
   EN_runH(ph, &t)                        solve hydraulics at time t
   EN_getnodevalue(i, EN_PRESSURE)        for every node
   EN_nextH(ph, &tstep)                   advance; tstep == 0 means finished
} while (tstep > 0)
EN_closeH ; EN_close ; EN_deleteproject
```

Build integration: `my-custom-app/CMakeLists.txt` pulls in the repo root with
`add_subdirectory(.. epanet EXCLUDE_FROM_ALL)` and links `epanet2`. Because of
`EXCLUDE_FROM_ALL`, only the library is built, not `runepanet`. Because the
include directory is `PUBLIC`, no extra include paths are needed.

### Notes

- **Extra time steps.** Net1 has a 24 h duration with a 1 h hydraulic step, but
  the simulation produces 27 steps. `nexthyd()` also stops at intermediate times
  when a tank fills or empties, or a control changes pump or valve status.
- **Tanks and reservoirs.** `EN_PRESSURE` is head minus elevation, so a reservoir
  reports 0 and a tank reports its water depth in pressure units.
- **Warnings.** Error codes 1–6 are warnings (for example, negative pressures). The
  app prints them to stderr and carries on. Codes above 100 stop the run.
- **Compiler warnings.** The engine build shows `-Wunused-result` warnings from
  upstream `project.c`, `report.c` and `util/filemanager.c`. These are upstream
  and harmless; the app itself compiles cleanly.
