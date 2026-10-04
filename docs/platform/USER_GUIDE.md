# City Infrastructure Designer – how to use it

The designer is for anyone preparing a first design for an engineer to review. You need no
engineering software and no internet connection. Everything runs on your own computer.

## Start it

* **Windows:** double-click `start-app.bat` in the project folder.
* **Mac or Linux:** double-click `start-app.sh`, or run `./start-app.sh` in a terminal.

Your web browser opens at `http://127.0.0.1:8765`. Keep the small black window open while you work,
and close it when you have finished.

The first start installs what the program needs, which takes a minute. You need Python 3.11 or newer
from python.org. On Windows, tick "Add Python to PATH" when you install it.

## Use it

1. **Pick what to design:** sewer lines, water supply, rainwater drains, roads, junctions or electricity.
2. **Draw.** Choose a tool on the left and click on the sheet:
   * place points such as manholes, tanks and transformers;
   * join two points with a pipe, drain or cable by clicking the first point and then the second;
   * draw a road by clicking at its start, at each bend and at its end. Double-click to finish. You
     can also hold the mouse button down and draw the road freehand;
   * draw a rain area by clicking around its edge, double-clicking to finish, then clicking the drain
     point its rain flows to.
3. **Fill in** the details in the panel on the right.
   * Values marked **Suggested – check this** were filled in for you. Confirm or change them.
   * Fields marked **Needed** must be filled in before the check can run.
   * For sewers and drains, **Fill in pipe levels for me** works out the pipe levels from the ground
     levels.
4. **Press Check my design.** Results are shown in plain words:

   | Colour | Meaning |
   |---|---|
   | Green | OK |
   | Amber | Check this |
   | Red | Problem |
   | Grey | Not checked, because some information is missing |

   Each problem says why it matters and **what to do**. **Show** takes you to the item on the drawing.
5. **Open the report** to get the full calculation for the engineer. You can print it or save it as a PDF.

**Save my work** downloads your drawing as a file, and **Open saved work** opens it again. The
program also remembers your last drawing in this browser.

To get your bearings, press **Load example** to see a finished design. **Undo** reverses that.

## Handy keys

| Key | What it does |
|---|---|
| Esc | Stop drawing, or close a panel |
| Enter | Finish a road or area |
| Delete | Delete the selected item |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| F1 | Help |
| Mouse wheel | Zoom |
| Drag empty space | Move around |

Every button and box explains itself when you point at it (or long-press it on a touch screen).

## What it does not do

* It does not approve a design. A qualified engineer must review every result. The design rules
  marked "needs confirming" in the report have not yet been checked against the printed codes.
* The example rainfall and the sample cable list are invented. They let you try the program, but a
  real design needs real rainfall figures and real cable data.
* Pavement thickness, RCC/structural design and quantities are not part of this program.
* Drawings use the project's map coordinates: UTM zone 43 N in metres (EPSG:32643). Files in
  longitude and latitude are refused rather than misread.

## For the engineer

* Each result's **Technical details** shows the calculated figures, the rule applied, and that rule's
  source and verification state.
* The report gives the full method and the design sheet, together with the simulation results from
  EPA SWMM and EPANET.
* The saved `.geojson` file can be opened with the command line (`cityinfra sewer my.geojson`) or in a
  GIS program.
