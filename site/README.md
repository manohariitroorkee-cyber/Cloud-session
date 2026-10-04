# Project web page

`index.html` and `images/` form a self-contained page describing the City Infrastructure Designer
and the work done so far. Copy both to any website (they only need a web server for static files).
You can also open `index.html` directly from disk.

* To edit the page in Visual Studio Code, open `index.html`. The *Live Server* extension shows your
  changes as you type.
* To refresh the screenshots, run
  `python ../backend/ui_audit/check_app.py shots` (or the scratch script used to make them), and save
  each image as `.webp` in `images/`.
* To publish it, upload `index.html` and the `images` folder together to the website's folder. GitHub Pages can
  serve it from a separate branch that holds just these files.

The page describes the program; it does not run it. Running the designer needs the Python server.
See `docs/platform/VSCODE_AND_WEBSITE.md`.
