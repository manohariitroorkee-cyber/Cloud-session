"""Design rainfall: IDF relationships and design-storm hyetographs.

The IDF relationship is PROJECT INPUT – it must come from IMD data or the
project hydrology report and is recorded with its source.  The platform
ships no default IDF for any city.

Supported forms
---------------
``{"form": "power", "source": "...", "return_periods": {"5": {"a": .., "b": .., "n": ..}}}``
    i (mm/h) = a / (t + b)^n,  t in minutes
``{"form": "table", "source": "...", "durations_min": [...], "return_periods": {"5": [i1, i2, ...]}}``
    log–log interpolation between tabulated durations (no extrapolation)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class IDF:
    spec: dict

    @property
    def source(self) -> str:
        return self.spec.get("source") or "IDF source not stated"

    def intensity(self, duration_min: float, return_period: int | float) -> float:
        rp = str(int(return_period)) if float(return_period).is_integer() else str(return_period)
        rps = self.spec["return_periods"]
        if rp not in rps:
            raise KeyError(f"IDF has no {rp}-year return period (available: {', '.join(rps)})")
        if duration_min <= 0:
            raise ValueError("duration must be positive")
        if self.spec["form"] == "power":
            c = rps[rp]
            return c["a"] / (duration_min + c["b"]) ** c["n"]
        if self.spec["form"] == "table":
            ds, iv = self.spec["durations_min"], rps[rp]
            if not ds[0] <= duration_min <= ds[-1]:
                raise ValueError(f"duration {duration_min:.1f} min outside IDF table {ds[0]}–{ds[-1]} min")
            for k in range(len(ds) - 1):
                if ds[k] <= duration_min <= ds[k + 1]:
                    f = (math.log(duration_min) - math.log(ds[k])) / (math.log(ds[k + 1]) - math.log(ds[k]))
                    return math.exp(math.log(iv[k]) + f * (math.log(iv[k + 1]) - math.log(iv[k])))
        raise ValueError(f"unknown IDF form {self.spec['form']!r}")


def alternating_block(idf: IDF, return_period: float, duration_min: int, step_min: int,
                      peak_position: float = 0.5) -> list[float]:
    """Design hyetograph by the alternating-block method (Chow, Maidment & Mays, 1988).

    Returns block intensities (mm/h), one per time step, whose cumulative
    depth for every duration up to ``duration_min`` matches the IDF.
    """
    n = duration_min // step_min
    if n < 1 or duration_min % step_min:
        raise ValueError("duration must be a whole multiple of the time step")
    cum = [idf.intensity((k + 1) * step_min, return_period) * (k + 1) * step_min / 60 for k in range(n)]
    inc = [cum[0]] + [cum[k] - cum[k - 1] for k in range(1, n)]          # mm, decreasing
    order = sorted(range(n), key=lambda k: -inc[k])
    blocks = [0.0] * n
    centre = min(n - 1, max(0, round(peak_position * (n - 1))))
    left, right = centre - 1, centre + 1
    blocks[centre] = inc[order[0]]
    for j, k in enumerate(order[1:]):
        place_right = (j % 2 == 0)
        if (place_right and right < n) or left < 0:
            blocks[right] = inc[k]; right += 1
        else:
            blocks[left] = inc[k]; left -= 1
    return [b * 60 / step_min for b in blocks]


def kirpich_tc_min(flow_length_m: float, slope: float) -> float:
    """Kirpich (1940), metric form: tc [min] = 0.0195 · L^0.77 · S^-0.385."""
    if flow_length_m <= 0 or slope <= 0:
        raise ValueError("flow length and slope must be positive")
    return 0.0195 * flow_length_m ** 0.77 * slope ** -0.385
