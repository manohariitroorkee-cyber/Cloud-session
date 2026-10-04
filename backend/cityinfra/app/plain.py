"""Plain-language wording for every design check.

Each check has: a short title for when it FAILS, one for when it PASSES, and an
explanation a non-engineer can follow ("why it matters").  The technical message
from the calculation is always shown alongside, so nothing is hidden.
A test makes sure every check produced anywhere in the code has an entry here.
"""

from __future__ import annotations

import html
import re

PLAIN: dict[str, tuple[str, str, str]] = {
    # ---- sewer
    "min_diameter": ("Pipe is smaller than the minimum allowed", "Pipe size is at least the minimum",
                     "Very small pipes block easily, so the rules set a smallest size."),
    "capacity": ("Pipe or drain is too small for the flow", "Pipe or drain can carry the flow",
                 "If more water arrives than the pipe can carry, it backs up and overflows."),
    "depth_ratio": ("Pipe runs too full", "Pipe has spare space above the flow",
                    "Pipes are designed to run part-full so air can move and peak flows fit."),
    "max_velocity": ("Water flows too fast", "Water speed is within the safe limit",
                     "Very fast water wears away the pipe or drain over time."),
    "min_velocity_design_peak": ("Water flows too slowly to keep the pipe clean", "Water moves fast enough to keep the pipe clean",
                                 "If sewage moves slowly, solids settle and the pipe chokes."),
    "min_velocity_present_peak": ("Flow is too slow in the early years", "Flow keeps the pipe clean even in the early years",
                                  "Before the area is fully built, there is less sewage; it still has to keep the pipe clean."),
    "manhole_spacing": ("Manholes are too far apart", "Manholes are close enough for cleaning",
                        "Workers clean sewers from manholes; they must not be too far apart."),
    "min_cover": ("Pipe is too close to the ground surface", "Pipe is buried deep enough",
                  "Pipes need enough soil on top so traffic and digging do not damage them."),
    "invert_continuity": ("Pipe leaving a manhole starts higher than the pipe coming in", "Levels at the manhole step down correctly",
                          "Sewage cannot flow uphill; the outgoing pipe must start at or below the incoming one."),
    "diameter_reduction": ("Pipe gets smaller downstream", "Pipe does not get smaller downstream",
                           "Flow only grows downstream, so a smaller pipe below a larger one will choke."),
    "crown_matching": ("Top of the bigger outgoing pipe is higher than the incoming pipe", "Pipe tops line up at the manhole",
                       "When the pipe gets bigger, its top should not be above the incoming pipe's top, or flow backs up."),
    # ---- water
    "min_residual_pressure": ("Water pressure is too low here", "Water pressure is enough here",
                              "With low pressure, water will not reach upper floors."),
    # ---- drainage
    "return_period": ("Design storm is weaker than recommended for this area", "Design storm strength is as recommended",
                      "Drains are sized for a storm that comes once in so many years; busier areas need rarer, heavier storms."),
    "runoff_coefficient": ("Runoff value is outside the usual range", "Runoff value is in the usual range",
                           "This number says how much rain runs off a surface instead of soaking in."),
    "freeboard": ("Open drain is too full (not enough spare height)", "Open drain has spare height above the water",
                  "Some spare height is kept so waves and debris do not overflow the drain."),
    "min_velocity": ("Water flows too slowly to keep the drain clean", "Water moves fast enough to keep the drain clean",
                     "Slow water lets silt settle and the drain chokes."),
    # ---- road
    "kink": ("Sharp corner with no curve", "No sharp corners",
             "Vehicles cannot turn at a point; every change of direction needs a curve."),
    "min_radius": ("Curve is too sharp for the speed", "Curve is gentle enough for the speed",
                   "On a sharp curve, vehicles at the design speed could skid or overturn."),
    "transition_length": ("Easing curve is too short", "Easing curve is long enough",
                          "A gradual easing curve lets drivers steer smoothly into the bend."),
    "transition_missing": ("Curve starts suddenly without an easing curve", "No easing curve needed here",
                           "Without a gradual entry, drivers must jerk the steering at the start of the bend."),
    "compound_ratio": ("Two joined curves are too different in sharpness", "Joined curves are similar in sharpness",
                       "A sudden change from a gentle to a sharp curve surprises drivers."),
    "broken_back": ("Short straight between two bends in the same direction", "Bends in the same direction are well separated",
                    "Drivers misjudge a short straight between two similar bends; one long curve is safer."),
    "reverse_curve": ("Not enough straight road between opposite bends", "Enough room between opposite bends",
                      "The road surface has to tilt the other way; that needs some length."),
    "max_grade": ("Road is too steep", "Road slope is within the limit", "Steep roads are hard for heavy vehicles."),
    "min_grade": ("Road is too flat for rainwater to drain", "Road slopes enough for rainwater to run off",
                  "On a very flat kerbed road, rainwater stands along the kerb."),
    "vertical_curve_length": ("Hump or dip is too short", "Hump or dip is smooth enough",
                              "Over a short hump drivers cannot see far enough ahead; a short dip is uncomfortable."),
    # ---- junction
    "intersection_angle": ("Roads meet at too sharp an angle", "Roads meet at a good angle",
                           "At a skewed junction drivers cannot easily see traffic coming from the side."),
    "number_of_arms": ("Too many roads meet here", "Number of roads meeting is manageable",
                       "More than four roads at one point confuses drivers; a roundabout may be better."),
    "corner_radius": ("Corner is too tight for buses and trucks", "Corner is wide enough for the design vehicle",
                      "Large vehicles need a wider corner, or they climb the kerb."),
    "sight_triangle": ("Something blocks the view at the corner", "Drivers can see each other in time",
                       "Drivers approaching a junction must see the other road early enough to stop."),
    "entry_radius": ("Roundabout entry curve is outside the recommended range", "Roundabout entry curve is in the recommended range",
                     "The entry curve controls how fast vehicles enter the roundabout."),
    "exit_radius": ("Roundabout exit curve is too tight", "Roundabout exit curve is fine",
                    "A gentle exit lets traffic leave the roundabout smoothly."),
    "central_island_radius": ("Roundabout centre island is too small", "Roundabout centre island is large enough",
                              "A bigger island slows vehicles and gives room to change lanes."),
    "weaving_length": ("Not enough room to change lanes between two roads", "Enough room to change lanes",
                       "Vehicles need some length to move across lanes between entering and leaving."),
    "weaving_capacity": ("Roundabout cannot handle the traffic", "Roundabout can handle the traffic",
                         "This estimates how many vehicles per hour the busiest section can carry."),
    # ---- electrical
    "cable_current": ("Cable is too thin for the load", "Cable can carry the load",
                      "An overloaded cable overheats and can fail or catch fire."),
    "voltage_drop": ("Voltage at the building is too low", "Voltage at the building is fine",
                     "Long or thin cables lose voltage; appliances then work poorly."),
    "transformer_loading": ("Transformer is overloaded", "Transformer has enough capacity",
                            "An overloaded transformer overheats and trips."),
}

# What a non-engineer can try first when a check fails.  Specific proposals worked out
# by the calculation (e.g. "use 300 mm") are shown before this general advice.
ADVICE: dict[str, str] = {
    "min_diameter": "Choose a bigger pipe size.",
    "capacity": "Choose a bigger pipe or drain, or make it slope more steeply.",
    "depth_ratio": "Choose a bigger pipe, or make it slope more steeply.",
    "max_velocity": "Make the pipe slope more gently (use drop manholes on steep ground).",
    "min_velocity_design_peak": "Make the pipe slope more steeply, or use a smaller pipe if it is oversized.",
    "min_velocity_present_peak": "Make the pipe slope more steeply; an engineer may accept this with regular flushing.",
    "manhole_spacing": "Add a manhole part-way along this pipe.",
    "min_cover": "Lower the pipe (deeper levels) or check the ground level you entered.",
    "invert_continuity": "Lower the start of the outgoing pipe to at or below the incoming pipe's end.",
    "diameter_reduction": "Make this pipe at least as big as the one above it.",
    "crown_matching": "Lower the bigger outgoing pipe so its top is level with, or below, the incoming pipe's top.",
    "min_residual_pressure": "Use bigger pipes on the way to this point, or a higher water tank.",
    "return_period": "Choose a rarer (heavier) design storm in the storm settings.",
    "runoff_coefficient": "Check the surface type chosen for this area.",
    "freeboard": "Make the drain deeper or wider.",
    "min_velocity": "Make the drain slope more steeply.",
    "kink": "Give this bend a curve radius.",
    "min_radius": "Make the bend gentler: enter a bigger radius.",
    "transition_length": "Enter a longer easing curve for this bend.",
    "transition_missing": "Enter an easing curve length for this bend.",
    "compound_ratio": "Make the two joined curves closer in radius.",
    "broken_back": "Join the two bends into one longer curve, or lengthen the straight between them.",
    "reverse_curve": "Move the bends further apart or use easing curves.",
    "max_grade": "Make the road less steep: change the start or end level.",
    "min_grade": "Give the road a little more slope so rainwater runs off.",
    "vertical_curve_length": "Make the hump or dip longer.",
    "intersection_angle": "Bring the roads closer to a right angle.",
    "number_of_arms": "Consider a roundabout, or move one road to meet elsewhere.",
    "corner_radius": "Make the corner wider (bigger corner radius).",
    "sight_triangle": "Remove or move whatever blocks the view at this corner.",
    "entry_radius": "Change the roundabout entry curve radius.",
    "exit_radius": "Make the roundabout exit curve bigger.",
    "central_island_radius": "Make the roundabout's centre island bigger.",
    "weaving_length": "Make the roundabout bigger so there is more room between roads.",
    "weaving_capacity": "Make the roundabout bigger or wider, or consider traffic signals.",
    "cable_current": "Choose a thicker cable or run two cables side by side.",
    "voltage_drop": "Choose a thicker cable, or place the transformer or feeder pillar closer to the buildings.",
    "transformer_loading": "Choose a bigger transformer, or split the buildings between two transformers.",
}

STATUS_WORD = {"pass": "OK", "fail": "Problem", "warning": "Check this", "not_evaluated": "Not checked"}


def plain(check: str, status: str) -> tuple[str, str]:
    """(title, why it matters) for a check result."""
    if check not in PLAIN:
        return check.replace("_", " ").capitalize(), ""
    bad, good, why = PLAIN[check]
    if status == "pass":
        return good, why
    if status == "not_evaluated":
        return f"Not checked: {good[0].lower() + good[1:]}", why
    return bad, why


# ---------------------------------------------------------- report markdown → HTML

def markdown_to_html(md: str) -> str:
    """Tiny converter for the report subset: headings, tables, lists, blockquotes, bold, code."""
    out, table, in_list = [], [], False

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", s)
        return s

    def flush_table():
        nonlocal table
        if table:
            rows = [r for r in table if not re.match(r"^\|[\s\-|:]+\|$", r)]
            h = "<table>" + "".join(
                "<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{inline(c.strip())}</{'th' if i == 0 else 'td'}>"
                                 for c in r.strip().strip("|").split("|")) + "</tr>"
                for i, r in enumerate(rows)) + "</table>"
            out.append(h)
            table = []

    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,4}) (.*)", line)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


REPORT_CSS = """body{font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#15212b}
table{border-collapse:collapse;margin:8px 0 16px;font-size:12.5px}td,th{border:1px solid #c9d3d9;padding:4px 7px;vertical-align:top}
th{background:#eef2f4;text-align:left}blockquote{border-left:4px solid #d03b3b;background:#fdf1f1;margin:12px 0;padding:8px 12px}
h1{font-size:22px}h2{font-size:17px;margin-top:26px}code{font-size:12px;word-break:break-all}
@media print{body{margin:0}}"""


def report_page(md: str, title: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{REPORT_CSS}</style></head><body>{markdown_to_html(md)}</body></html>")
