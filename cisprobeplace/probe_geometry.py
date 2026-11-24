from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from .models import PinRecord
from .script_builder import classify_pin_sides


@dataclass(frozen=True)
class _Band:
    side: str
    indices: tuple[int, ...]
    outer: frozenset[int]
    separation: float
    pitch: float


def infer_bond_layout(pins: Sequence[PinRecord]) -> tuple[list[str], list[str | None]]:
    """Infer axis-aligned staggered bonding lanes; retain legacy SIDE otherwise.

    ``outer``/``inner`` describe pad positions relative to the layout interior,
    never a measured probe length. One unsupported strip has no known polarity.
    Irregular arrays reproducing a supported strip remain geometrically ambiguous.
    """
    sides = classify_pin_sides(pins)
    lanes: list[str | None] = [None] * len(pins)
    if len(pins) < 8:
        return sides, lanes
    coordinates = [(pin.pin_x, pin.pin_y) for pin in pins]
    bands: dict[tuple[str, tuple[int, ...]], _Band] = {}
    rows: dict[tuple[str, tuple[int, ...]], tuple[int, ...]] = {}
    for axis in (0, 1):
        ordered = sorted(range(len(pins)), key=lambda index: coordinates[index][axis])
        low, high = coordinates[ordered[0]][axis], coordinates[ordered[-1]][axis]
        span = high - low
        if span <= 0:
            continue
        # A short fixed scale sweep accommodates roundoff and small pad jitter.
        tolerance = span * 1e-9
        while tolerance <= span * 0.025:
            clusters: list[list[int]] = []
            for index in ordered:
                if not clusters or coordinates[index][axis] - coordinates[clusters[-1][-1]][axis] > tolerance:
                    clusters.append([index])
                else:
                    clusters[-1].append(index)
            populated = [cluster for cluster in clusters if len(cluster) >= 4]
            for cluster in populated:
                normal_low = coordinates[cluster[0]][axis]
                normal_high = coordinates[cluster[-1]][axis]
                tangent = [coordinates[index][1 - axis] for index in cluster]
                tangent_span = max(tangent) - min(tangent)
                if tangent_span > 0 and normal_high - normal_low <= tangent_span * 0.025:
                    if normal_low - low <= span * 0.15:
                        side = "left" if axis == 0 else "bottom"
                        rows[(side, tuple(sorted(cluster)))] = tuple(cluster)
                    if high - normal_high <= span * 0.15:
                        side = "right" if axis == 0 else "top"
                        rows[(side, tuple(sorted(cluster)))] = tuple(cluster)
            for index in range(len(populated) - 1):
                first, second = populated[index:index + 2]
                band = _staggered_band(first, second, populated, index, coordinates, axis, low, high)
                if band is not None:
                    bands[(band.side, tuple(sorted(band.indices)))] = band
            tolerance *= 4
    # Prefer the complete strip over a subset that appeared at a tighter tolerance.
    candidates = sorted(bands.values(), key=lambda band: (-len(band.indices), band.side, band.indices))
    accepted: list[_Band] = []
    for band in candidates:
        indices = set(band.indices)
        if any(band.side == other.side and indices.intersection(other.indices) for other in accepted):
            continue
        axis = 0 if band.side in ("left", "right") else 1
        normal = [coordinates[index][axis] for index in band.indices]
        normal_center = median(normal)
        inward = 1 if band.side in ("left", "bottom") else -1
        supported = False
        for (row_side, _), row in rows.items():
            remaining = [index for index in row if index not in indices]
            if row_side == band.side or len(remaining) < 4:
                continue
            # The supporting row must extend into the interior, beyond both lanes.
            depth = max((coordinates[index][axis] - normal_center) * inward for index in remaining)
            if depth > max(band.separation * 2, band.pitch * 2):
                supported = True
                break
        if supported:
            accepted.append(band)
    membership: dict[int, list[_Band]] = {}
    for band in accepted:
        for index in band.indices:
            membership.setdefault(index, []).append(band)
    row_axes: dict[int, set[int]] = {}
    for (side, _), indices in rows.items():
        axis = 0 if side in ("left", "right") else 1
        for index in indices:
            row_axes.setdefault(index, set()).add(axis)
    for index, matches in membership.items():
        axis = 0 if matches[0].side in ("left", "right") else 1
        if len(matches) == 1 and 1 - axis not in row_axes.get(index, ()):
            sides[index] = matches[0].side
            lanes[index] = "outer" if index in matches[0].outer else "inner"
    return sides, lanes


def _staggered_band(
    first: list[int], second: list[int], clusters: list[list[int]], position: int,
    coordinates: list[tuple[float, float]], axis: int, low: float, high: float,
) -> _Band | None:
    first_normal = [coordinates[index][axis] for index in first]
    second_normal = [coordinates[index][axis] for index in second]
    separation = median(second_normal) - median(first_normal)
    if separation <= 0 or max(max(first_normal) - min(first_normal), max(second_normal) - min(second_normal)) > separation * 0.15:
        return None
    first_tangent = [coordinates[index][1 - axis] for index in first]
    second_tangent = [coordinates[index][1 - axis] for index in second]
    tangent_span = max(first_tangent + second_tangent) - min(first_tangent + second_tangent)
    overlap = min(max(first_tangent), max(second_tangent)) - max(min(first_tangent), min(second_tangent))
    if tangent_span <= 0 or overlap < tangent_span * 0.4 or separation > tangent_span * 1.5:
        return None
    combined = sorted(first + second, key=lambda index: coordinates[index][1 - axis])
    gaps = [coordinates[b][1 - axis] - coordinates[a][1 - axis] for a, b in zip(combined, combined[1:])]
    pitch = median(gaps)
    if pitch <= 0 or min(gaps) < pitch * 0.05 or separation < pitch * 0.1:
        return None
    first_ids = set(first)
    transitions = sum((a in first_ids) != (b in first_ids) for a, b in zip(combined, combined[1:]))
    # Real SPD sites omit shared nets (e.g. GND), leaving same-lane steps in staggered rows.
    if transitions < (len(combined) - 1) * 0.65 or min(len(first), len(second)) < len(combined) * 0.35:
        return None
    # A third similar neighboring row indicates a filled array, not two bonding lanes.
    for neighbor_position in (position - 1, position + 2):
        if 0 <= neighbor_position < len(clusters):
            neighbor = clusters[neighbor_position]
            normal = median(coordinates[index][axis] for index in neighbor)
            distance = min(abs(normal - median(first_normal)), abs(normal - median(second_normal)))
            tangent = [coordinates[index][1 - axis] for index in neighbor]
            neighbor_overlap = min(max(tangent), max(first_tangent + second_tangent)) - max(min(tangent), min(first_tangent + second_tangent))
            if distance <= separation * 2 and neighbor_overlap >= tangent_span * 0.4:
                return None
    center = (median(first_normal) + median(second_normal)) / 2
    if abs(center - (low + high) / 2) <= separation * 1.5:
        return None
    nearer_low = center < (low + high) / 2
    outer_normal = min(first_normal) if nearer_low else max(second_normal)
    if min(abs(outer_normal - low), abs(high - outer_normal)) > (high - low) * 0.03:
        return None
    side = ("left" if nearer_low else "right") if axis == 0 else ("bottom" if nearer_low else "top")
    return _Band(side, tuple(combined), frozenset(first if nearer_low else second), separation, pitch)
