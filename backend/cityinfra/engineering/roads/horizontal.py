"""Backward-compatible entry point: PI-based horizontal alignment.

The geometry engine lives in ``alignment.py`` (lines, arcs and clothoids of
any combination).  ``build(pis, curves)`` keeps the original call form:
curves = {pi_index: (radius, transition_length)} or any spec accepted by
``alignment.normalise_spec``.
"""

from .alignment import Alignment as HorizontalAlignment  # noqa: F401
from .alignment import CurveGroup, Element, from_pis  # noqa: F401


def build(pis, curves) -> HorizontalAlignment:
    return from_pis([tuple(p) for p in pis], curves)
