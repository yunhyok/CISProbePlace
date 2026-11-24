import pytest

from cisprobeplace.models import GenerationOptions, PinRecord
from cisprobeplace.script_builder import build_script, classify_pin_side, source_group_name_for_comp_device


def test_classify_pin_side_uses_nearest_bounding_box_edge_with_tie_priority():
    pins = [
        PinRecord("U", "R", "SYM", "LONG", "PAD", 10.0, 5.0, "NR"),
        PinRecord("U", "T", "SYM", "LONG", "PAD", 5.0, 10.0, "NT"),
        PinRecord("U", "L", "SYM", "SHORT", "PAD", 0.0, 5.0, "NL"),
        PinRecord("U", "B", "SYM", "SHORT", "PAD", 5.0, 0.0, "NB"),
        PinRecord("U", "C", "SYM", "SHORT", "PAD", 5.0, 5.0, "NC"),
    ]

    assert classify_pin_side(pins[0], pins) == "right"
    assert classify_pin_side(pins[1], pins) == "top"
    assert classify_pin_side(pins[2], pins) == "left"
    assert classify_pin_side(pins[3], pins) == "bottom"
    assert classify_pin_side(pins[4], pins) == "right"


def test_classify_pin_side_does_not_invent_missing_right_side_from_top_edge_endpoints():
    pins = [
        PinRecord("", "L1", "", "", "", 0.0, 2.0, "N"),
        PinRecord("", "L2", "", "", "", 1.0, 3.0, "N"),
        PinRecord("", "L3", "", "", "", 0.0, 4.0, "N"),
        PinRecord("", "L4", "", "", "", 1.0, 5.0, "N"),
        PinRecord("", "B1", "", "", "", 3.0, 0.0, "N"),
        PinRecord("", "B2", "", "", "", 4.0, 1.0, "N"),
        PinRecord("", "B3", "", "", "", 5.0, 0.0, "N"),
        PinRecord("", "B4", "", "", "", 6.0, 1.0, "N"),
        PinRecord("", "T1", "", "", "", 3.0, 9.0, "N"),
        PinRecord("", "T2", "", "", "", 4.0, 10.0, "N"),
        PinRecord("", "T3", "", "", "", 7.0, 9.0, "N"),
        PinRecord("", "T4", "", "", "", 8.0, 10.0, "N"),
        PinRecord("", "T5", "", "", "", 9.0, 9.0, "N"),
    ]

    classified = {pin.pin_number: classify_pin_side(pin, pins) for pin in pins}

    assert classified["T3"] == "top"
    assert classified["T4"] == "top"
    assert classified["T5"] == "top"
    assert "right" not in classified.values()


def test_source_group_name_uses_sanitized_comp_device():
    assert source_group_name_for_comp_device("CIS LONG/TYPE-1") == "Source_CIS_LONG_TYPE_1"
    assert source_group_name_for_comp_device("") == "Source_EMPTY"


def test_build_script_generates_cis_side_angle_variables_and_source_groups():
    pins = [
        PinRecord("U", "R", "SYM", "CIS_LONG", "PAD", 10.0, 5.0, "NR"),
        PinRecord("U", "T", "SYM", "CIS_LONG", "PAD", 5.0, 10.0, "NT"),
        PinRecord("U", "L", "SYM", "CIS_SHORT", "PAD", 0.0, 5.0, "NL"),
        PinRecord("U", "B", "SYM", "CIS_SHORT", "PAD", 5.0, 0.0, "DGND"),
    ]

    result = build_script(
        pins,
        GenerationOptions(
            project_name="Project1",
            design_name="HFSSDesign1",
            right_rotation_angle=0,
            top_rotation_angle=90,
            left_rotation_angle=180,
            bottom_rotation_angle=270,
        ),
    )

    assert 'ensure_design_variable("CISRotAng_Right", "0deg")' in result.script
    assert 'ensure_design_variable("CISRotAng_Top", "90deg")' in result.script
    assert 'ensure_design_variable("CISRotAng_Left", "180deg")' in result.script
    assert 'ensure_design_variable("CISRotAng_Bottom", "270deg")' in result.script
    assert '"R", "NR", 10, 5, "right", "Source_CIS_LONG", "CISRotAng_Right"' in result.script
    assert '"T", "NT", 5, 10, "top", "Source_CIS_LONG", "CISRotAng_Top"' in result.script
    assert '"L", "NL", 0, 5, "left", "Source_CIS_SHORT", "CISRotAng_Left"' in result.script
    assert '"B", "DGND", 5, 0, "bottom", "Source_CIS_SHORT", "CISRotAng_Bottom"' in result.script
    assert 'duplicate_and_get_new_object(source_name, angle_variable)' in result.script
    assert '"AngleStr:="          , angle_variable,' in result.script
    assert "validate_source_groups" in result.script
    assert "Missing HFSS source group" in result.script
    assert "Prepare a non-empty HFSS group" in result.script
    assert "assign_perfect_e(perf_e_name, sheet_clones)" in result.script


def test_build_script_handles_three_sided_cis_layout():
    pins = [
        PinRecord("U", "R", "SYM", "CIS_A", "PAD", 10.0, 5.0, "NR"),
        PinRecord("U", "T", "SYM", "CIS_A", "PAD", 5.0, 10.0, "NT"),
        PinRecord("U", "L", "SYM", "CIS_B", "PAD", 0.0, 5.0, "NL"),
    ]

    result = build_script(pins, GenerationOptions())

    assert '"R", "NR", 10, 5, "right", "Source_CIS_A", "CISRotAng_Right"' in result.script
    assert '"T", "NT", 5, 10, "top", "Source_CIS_A", "CISRotAng_Top"' in result.script
    assert '"L", "NL", 0, 5, "left", "Source_CIS_B", "CISRotAng_Left"' in result.script
    assert "CISRotAng_Bottom" in result.script

def test_build_script_uses_source_probe_name_as_hfss_group_directly():
    pins = [
        PinRecord("", "1", "", "", "", 10.0, 5.0, "SIGNAL_A", "LongProbe"),
        PinRecord("", "2", "", "", "", 5.0, 10.0, "SIGNAL_B", "ShortProbe"),
        PinRecord("", "3", "", "", "", 0.0, 5.0, "DGND", ""),
    ]

    result = build_script(pins, GenerationOptions())

    assert '"1", "SIGNAL_A", 10, 5, "right", "LongProbe", "CISRotAng_Right"' in result.script
    assert '"2", "SIGNAL_B", 5, 10, "top", "ShortProbe", "CISRotAng_Top"' in result.script
    assert '"3", "DGND", 0, 5, "left", "Source_Group", "CISRotAng_Left"' in result.script
    assert '("LongProbe", "LongProbe")' in result.script
    assert '("ShortProbe", "ShortProbe")' in result.script
    assert '("Source_Group", "Source_Group")' in result.script


def test_build_script_coordinate_rows_without_source_probe_use_source_group():
    pins = [
        PinRecord("", "1", "", "", "", 0.0, 0.0, "N1"),
        PinRecord("", "2", "", "", "", 10.0, 1.0, "N2"),
    ]

    result = build_script(pins, GenerationOptions())

    assert '"1", "N1", 0, 0, "left", "Source_Group"' in result.script
    assert '"2", "N2", 10, 1, "right", "Source_Group"' in result.script
    assert 'Source_EMPTY' not in result.script


def test_build_script_keeps_allegro_comp_device_fallback_when_no_source_probe_name():
    pins = [PinRecord("U1", "1", "SYM", "CIS_LONG", "PAD", 1.0, 2.0, "N1")]

    result = build_script(pins, GenerationOptions())

    assert '"1", "N1", 1, 2, "right", "Source_CIS_LONG", "CISRotAng_Right"' in result.script



def _aligned_ring_pins():
    pins = []
    for y in range(1, 10):
        pins.append(PinRecord("", f"L{y}", "", "", "", 0.0, float(y), "N"))
        pins.append(PinRecord("", f"R{y}", "", "", "", 10.0, float(y), "N"))
    for x in range(1, 10):
        pins.append(PinRecord("", f"T{x}", "", "", "", float(x), 10.0, "N"))
        pins.append(PinRecord("", f"B{x}", "", "", "", float(x), 0.0, "N"))
    return pins


def test_classify_pin_side_keeps_aligned_ring_pins_on_their_own_side():
    # Pads that line up across opposite sides share X or Y values, so every
    # corner-area pin also sits on a short crossing line of the other axis.
    pins = _aligned_ring_pins()
    expected = {"L": "left", "R": "right", "T": "top", "B": "bottom"}

    misclassified = {
        pin.pin_number: classify_pin_side(pin, pins)
        for pin in pins
        if classify_pin_side(pin, pins) != expected[pin.pin_number[0]]
    }

    assert misclassified == {}


def test_classify_pin_side_keeps_two_aligned_rows_as_top_and_bottom():
    pins = [PinRecord("", f"T{x}", "", "", "", float(x), 4.0, "N") for x in range(10)]
    pins += [PinRecord("", f"B{x}", "", "", "", float(x), 0.0, "N") for x in range(10)]

    classified = {pin.pin_number: classify_pin_side(pin, pins) for pin in pins}

    assert {side for number, side in classified.items() if number.startswith("T")} == {"top"}
    assert {side for number, side in classified.items() if number.startswith("B")} == {"bottom"}


def test_classify_pin_sides_matches_single_pin_classification():
    from cisprobeplace.script_builder import classify_pin_sides

    layouts = [
        _aligned_ring_pins(),
        [
            PinRecord("U", "R", "SYM", "LONG", "PAD", 10.0, 5.0, "NR"),
            PinRecord("U", "T", "SYM", "LONG", "PAD", 5.0, 10.0, "NT"),
            PinRecord("U", "L", "SYM", "SHORT", "PAD", 0.0, 5.0, "NL"),
            PinRecord("U", "B", "SYM", "SHORT", "PAD", 5.0, 0.0, "NB"),
            PinRecord("U", "C", "SYM", "SHORT", "PAD", 5.0, 5.0, "NC"),
        ],
        [PinRecord("", "1", "", "", "", 3.0, 4.0, "N")],
    ]

    for pins in layouts:
        assert classify_pin_sides(pins) == [classify_pin_side(pin, pins) for pin in pins]
    assert classify_pin_sides([]) == []


def test_build_script_classifies_large_layouts_without_quadratic_slowdown():
    import time

    # 20,000 pins on a ring. Classifying each pin against the whole layout from
    # scratch took minutes at this size; one shared analysis takes well under a second.
    per_side = 5000
    pins = []
    for index in range(per_side):
        offset = 1.0 + index * 0.01
        pins.append(PinRecord("", f"L{index}", "", "", "", 0.0, offset, "N"))
        pins.append(PinRecord("", f"R{index}", "", "", "", 60.0, offset, "N"))
        pins.append(PinRecord("", f"T{index}", "", "", "", offset, 60.0, "N"))
        pins.append(PinRecord("", f"B{index}", "", "", "", offset, 0.0, "N"))

    started = time.perf_counter()
    result = build_script(pins, GenerationOptions())
    elapsed = time.perf_counter() - started

    assert result.script.count('"CISRotAng_Left"),') == per_side
    assert result.script.count('"CISRotAng_Top"),') == per_side
    assert elapsed < 20.0


def test_classify_pin_side_gives_a_single_straight_line_one_side():
    row = [PinRecord("", str(x), "", "", "", float(x), 2.0, "N") for x in range(6)]
    column = [PinRecord("", str(y), "", "", "", 2.0, float(y), "N") for y in range(6)]

    # The end pins also touch the left/right (or top/bottom) edge of the bounding
    # box, but a single line can only be one side.
    assert {classify_pin_side(pin, row) for pin in row} == {"top"}
    assert {classify_pin_side(pin, column) for pin in column} == {"right"}


def test_export_of_one_pin_keeps_its_side_and_source_group():
    pin = PinRecord("SITE0", "A4", "", "", "", -2, 3, "CLK/0", "FineProbe")
    script = build_script([pin], pin_sides=["left"]).script
    assert '("A4", "CLK/0", -2, 3, "left", "FineProbe", "CISRotAng_Left")' in script


@pytest.mark.parametrize("sides", [[], ["left", "top"], ["unknown"]])
def test_rejects_invalid_side_assignment(sides):
    pin = PinRecord("", "1", "", "", "", 0, 0, "NET")
    with pytest.raises(ValueError, match="one side"):
        build_script([pin], pin_sides=sides)
