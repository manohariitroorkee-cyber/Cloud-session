# User-interface rule: every control explains itself

Adopted 4 Oct 2026 for all user interfaces of the platform (the current Network Designer page,
the command line, and the GIS frontend still to be built).

## The rule

1. **Every button, tool, tab and field says what it does.** The user never has to guess.
2. **One registry per interface** holds each control's *name*, *what it does* (one plain sentence,
   written for a site engineer, not a programmer) and its *shortcut*. Nothing is described twice.
3. The registry drives all the places help appears:
   * a **tooltip** on mouse hover, on keyboard focus, and on long-press on a touch screen;
   * a **status line** at the bottom of the window that explains whatever is being pointed at;
   * a **Help guide** (button and F1) with *Get started in four steps* and a table of every control,
     opened automatically on the first visit;
   * an **automated audit** that fails the build if any visible control has no description.
4. Buttons keep **visible text labels**; icons are never the only clue.
5. Help text describes the *effect*, including anything that cannot be undone, and says when an
   action asks for confirmation.

## Where it is implemented

| Interface | Registry | Audit |
|---|---|---|
| Network Designer (`index.html`) | `web-src/help.js` (`HELP` for controls, `FIELDS` for properties fields) | `NODE_PATH=$(npm root -g) node web-src/check-help.cjs` – opens the page in Chromium, walks through every state (each item type selected, after a run, export dialog, confirmation, guide) and lists any control without help |
| Command line (`cityinfra`) | `argparse` help on every option, with examples (`cityinfra -h`) | `backend/tests/test_cli_help.py` |
| City Infrastructure Designer (`backend/cityinfra/app/`) | the `data-help` attribute on each control (fields carry it on their label); the Help guide is built from those attributes, and every check's plain wording and advice live in `plain.py` | `backend/ui_audit/check_app.py` – walks every module (empty sheet, each tool, example, missing-details list, results, every kind of object selected, guide) at desktop and phone width; `backend/tests/test_app.py` – every check has wording and advice, every button in `app.js` has `data-help` |
| GIS frontend (to be built) | same pattern: one registry module | same audit approach, run in CI |

## Adding a new control

Add one line to the registry (selector, group, name, what it does, shortcut). The tooltip, status
line, guide and audit pick it up automatically; the audit fails until this is done.
