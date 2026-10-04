# Working in Visual Studio Code, and putting the designer on a website

## 1. Open the project in VS Code

You need three free programs:

* **Python 3.11 or newer** from python.org. On Windows, tick *Add Python to PATH* when you install it.
* **Visual Studio Code** from code.visualstudio.com.
* **Git** from git-scm.com. This is only needed to clone the repository; it is not needed if you use the zip.

You can open the project in either of two ways.

**From the zip.** Unzip `CityInfraDesigner.zip`, then in VS Code choose *File → Open Folder…* and pick
the unzipped `CityInfraDesigner` folder. The zip already contains the Windows calculation engines
(`engines/lib/epanet2.dll`, `swmm5.dll`).

**From GitHub.** Press F1, choose *Git: Clone*, and paste
`https://github.com/manohariitroorkee-cyber/Cloud-session.git`. Then switch to the branch
`platform/foundation-stage1` using the branch name at the bottom-left of the window. A clone has no
engine DLLs. Run task 4 (below), or copy them from the zip into `engines/lib/`.

When VS Code offers to install the recommended extensions (Python and others), accept.

## 2. Run it from VS Code

The project includes ready-made VS Code settings in the `.vscode` folder.

| What you want | How |
|---|---|
| Install what it needs (first time only) | *Terminal → Run Task… → 1. Install* |
| Start the designer | *Terminal → Run Task… → 2. Start the app*, or press **F5** and choose *City Infrastructure Designer*. The browser opens at http://127.0.0.1:8765 |
| Run all tests | *Terminal → Run Task… → 3. Run all tests*, or use the Testing panel (flask icon) |
| Build the engines yourself | *Run Task… → 4.* (needs CMake and Visual Studio Build Tools on Windows) |
| Check every screen in a browser | *Run Task… → 5.* (needs `pip install playwright` and `python -m playwright install chromium`) |

To stop the app, click in the terminal panel and press Ctrl+C.

## 3. Where things are

| Folder or file | What it holds |
|---|---|
| `backend/cityinfra/app/` | The designer: `static/` is the page (HTML, CSS, JavaScript), `api.py` turns checks into plain words, `server.py` is the local web server |
| `backend/cityinfra/engineering/` | The calculations: `sewer/`, `water/`, `drainage/` (including `existing.py` and `autodesign.py`), `roads/`, `electrical/` |
| `backend/cityinfra/rules/rulesets/*.yaml` | The design rules (CPHEEO, IRC, project decisions). Each value shows its source and whether it is verified. **Change values here, not in the code.** |
| `backend/cityinfra/reports/` | The reports for the engineer |
| `backend/tests/` | 148 automatic tests |
| `database/` | PostGIS database scripts (for the later multi-user version) |
| `docs/platform/` | Architecture, plan, audit, user guide, and this file |
| `engines/` | Scripts that build EPA SWMM and EPANET; `lib/` holds the built engines |

Because the page is plain HTML, CSS and JavaScript, editing anything in `backend/cityinfra/app/static/`
only needs a browser refresh. No build step is needed.

## 4. Putting it on a website

The designer is **not a static website**. Each check runs Python calculations and the SWMM and
EPANET engines on the server. Uploading the HTML alone to a web host will therefore show the page,
but every check will fail.

There are three ways to make it reachable by others. All three must have a login in front of them,
because the app itself has none.

**A. A computer on the office network (simplest).**
1. On a Windows PC or server, start it with
   `py -3 -m cityinfra.app --host 0.0.0.0 --port 8765 --no-browser` (from the `backend` folder).
2. Colleagues open `http://<that-computer's-IP>:8765`.
3. Allow port 8765 in that computer's firewall, for the office network only.

**B. A Linux server or cloud virtual machine with Docker.** The included `Dockerfile` builds
everything, including the engines:

```bash
docker build -t cityinfra .
docker run -d --restart unless-stopped -p 8765:8765 cityinfra
```

Put a reverse proxy (nginx, or the cloud provider's) in front of it with HTTPS and a login. The
automatic checks build and start this image on every change, so it is known to work.

**C. A Python hosting service** (any service that runs a Docker image or a Python web process). Point
the service at the repository and its `Dockerfile`. The app reads the port the service gives it from
the `PORT` setting.

Before you choose B or C, follow your department's rules on putting government project data on outside
servers. For official use, option A or a NIC/departmental server is the safer choice.

## 5. Saving your changes back to GitHub (from VS Code)

1. In the *Source Control* panel (branch icon), type a message and press **Commit**.
2. Then press **Sync Changes**.
3. Each push runs the automatic checks, which show green or red under *Actions* on GitHub:
   * tests on Linux and on Windows;
   * the browser walk-through;
   * the database scripts;
   * the Docker image.
