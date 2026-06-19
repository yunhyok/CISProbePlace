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
            top_rotation_angle=270,
            left_rotation_angle=180,
            bottom_rotation_angle=90,
        ),
    )

    assert 'ensure_design_variable("CISRotAng_Right", "0")' in result.script
    assert 'ensure_design_variable("CISRotAng_Top", "270")' in result.script
    assert 'ensure_design_variable("CISRotAng_Left", "180")' in result.script
    assert 'ensure_design_variable("CISRotAng_Bottom", "90")' in result.script
    assert '"R", "NR", 10, 5, "right", "Source_CIS_LONG", "CISRotAng_Right"' in result.script
    assert '"T", "NT", 5, 10, "top", "Source_CIS_LONG", "CISRotAng_Top"' in result.script
    assert '"L", "NL", 0, 5, "left", "Source_CIS_SHORT", "CISRotAng_Left"' in result.script
    assert '"B", "DGND", 5, 0, "bottom", "Source_CIS_SHORT", "CISRotAng_Bottom"' in result.script
    assert 'duplicate_and_get_new_object(source_name, angle_variable)' in result.script
    assert '"AngleStr:="          , angle_variable,' in result.script
    assert "validate_source_groups" in result.script
    assert "Missing HFSS source group for COMP_DEVICE" in result.script
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


