import itertools
import random
import time
from dataclasses import replace

import pytest

from cisprobeplace.models import PinRecord
from cisprobeplace.probe_geometry import infer_bond_layout
from cisprobeplace.script_builder import classify_pin_sides


SIDES = ("right", "top", "left", "bottom")
CONFIGURATIONS = [sides for count in (2, 3, 4) for sides in itertools.combinations(SIDES, count)]


def layout(sides=SIDES, count=12, *, noise=0, scale=1, offset=(0, 0), single=()):
    rng = random.Random(1729)
    records, expected_sides, expected_lanes = [], [], []
    for side in sides:
        for index in range(count):
            tangent = -6 + index * 12 / (count - 1)
            lane = "outer" if index % 2 == 0 else "inner"
            normal = 12 if lane == "outer" else 10
            if side in single:
                normal, lane = 12, None
            normal *= -1 if side in ("left", "bottom") else 1
            x, y = (normal, tangent) if side in ("left", "right") else (tangent, normal)
            x = (x + rng.uniform(-noise, noise)) * scale + offset[0]
            y = (y + rng.uniform(-noise, noise)) * scale + offset[1]
            records.append(PinRecord("DUT", f"{side}-{index}", "", "", "", x, y, "N"))
            expected_sides.append(side)
            expected_lanes.append(lane)
    return records, expected_sides, expected_lanes


@pytest.mark.parametrize("active_sides", CONFIGURATIONS)
@pytest.mark.parametrize("noise", (0, 0.002))
def test_two_three_four_sided_staggered_rows_infer_each_original_pin(active_sides, noise):
    records, sides, lanes = layout(active_sides, noise=noise)
    assert infer_bond_layout(records) == (sides, lanes)


@pytest.mark.parametrize("scale,offset", [(0.001, (-500, 600)), (1000, (2e6, -9e5))])
def test_translation_scale_permutation_preserve_relative_lanes(scale, offset):
    records, sides, lanes = layout(("left", "top"), noise=0.001, scale=scale, offset=offset)
    order = list(range(len(records)))
    random.Random(7).shuffle(order)
    assert infer_bond_layout([records[index] for index in order]) == (
        [sides[index] for index in order], [lanes[index] for index in order])


def test_interleaved_unequal_tangential_pitch_is_not_required_to_be_uniform():
    records, sides, lanes = [], [], []
    for side in SIDES:
        for lane, normal, tangents in (("outer", 12, (-6, -2, 2, 6)), ("inner", 10, (-5, -1, 3, 7))):
            for tangent in tangents:
                signed = -normal if side in ("left", "bottom") else normal
                x, y = (signed, tangent) if side in ("left", "right") else (tangent, signed)
                records.append(PinRecord("", str(len(records)), "", "", "", x, y, ""))
                sides.append(side)
                lanes.append(lane)
    assert infer_bond_layout(records) == (sides, lanes)


@pytest.mark.parametrize("single", [("top",), ("left", "right", "bottom")])
def test_clear_other_single_rows_support_only_the_staggered_side(single):
    records, sides, lanes = layout(single=single)
    assert infer_bond_layout(records) == (sides, lanes)


def test_one_staggered_side_supported_by_an_adjacent_single_row():
    records, sides, lanes = layout(("top", "left"), single=("left",))
    assert infer_bond_layout(records) == (sides, lanes)


def test_unilateral_strip_and_sparse_lanes_remain_undetermined():
    for active_sides, count in [(("top",), 12), (("left", "bottom"), 4)]:
        records, _, _ = layout(active_sides, count=count)
        assert infer_bond_layout(records) == (classify_pin_sides(records), [None] * len(records))
    assert infer_bond_layout([]) == ([], [])


def test_aligned_parallel_rows_are_not_long_short_groups():
    records = []
    for side in SIDES:
        for normal in (10, 12):
            for tangent in (-6, -2, 2, 6):
                normal_signed = -normal if side in ("left", "bottom") else normal
                x, y = (normal_signed, tangent) if side in ("left", "right") else (tangent, normal_signed)
                records.append(PinRecord("", str(len(records)), "", "", "", x, y, ""))
    assert infer_bond_layout(records) == (classify_pin_sides(records), [None] * len(records))


@pytest.mark.parametrize("stagger", (0, 0.5))
def test_filled_grids_and_staggered_arrays_do_not_become_two_lane_sides(stagger):
    records = [PinRecord("", f"{x}-{y}", "", "", "", x + stagger * (y % 2), float(y), "")
               for y in range(10) for x in range(12)]
    assert infer_bond_layout(records) == (classify_pin_sides(records), [None] * len(records))


def test_incidental_alternating_jitter_in_single_rows_is_not_a_second_lane():
    records, _, _ = layout(single=SIDES)
    jittered = []
    for index, record in enumerate(records):
        shift = 0.001 if index % 2 else -0.001
        if record.pin_number.startswith(("left", "right")):
            jittered.append(replace(record, pin_x=record.pin_x + shift))
        else:
            jittered.append(replace(record, pin_y=record.pin_y + shift))
    assert infer_bond_layout(jittered) == (classify_pin_sides(jittered), [None] * len(jittered))


def test_non_alternating_two_lanes_do_not_invent_probe_types():
    records, _, _ = layout()
    mixed = []
    for index, record in enumerate(records):
        side = record.pin_number.split("-")[0]
        normal = (12 if index % 12 < 6 else 10) * (-1 if side in ("left", "bottom") else 1)
        mixed.append(replace(record, **({"pin_x": normal} if side in ("left", "right") else {"pin_y": normal})))
    assert infer_bond_layout(mixed) == (classify_pin_sides(mixed), [None] * len(mixed))


def test_corner_on_both_perpendicular_pad_rows_has_no_invented_type():
    records, _, _ = layout()
    records.append(PinRecord("", "corner", "", "", "", -12, 12, ""))
    _, lanes = infer_bond_layout(records)
    assert lanes[-1] is None


def test_twenty_five_thousand_pins_are_classified_without_quadratic_work():
    records, sides, lanes = layout(count=6250)
    started = time.perf_counter()
    assert infer_bond_layout(records) == (sides, lanes)
    # Generous ceiling catches accidental per-pin all-pairs scans on a desktop.
    assert time.perf_counter() - started < 12
