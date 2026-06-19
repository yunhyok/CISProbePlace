from cisprobeplace.models import GenerationOptions, PinRecord
from cisprobeplace.script_builder import build_script, sanitize_aedt_name


def test_sanitize_aedt_name_replaces_unstable_characters():
    assert sanitize_aedt_name("1_NET/A Obj-1") == "1_NET_A_Obj_1"
    assert sanitize_aedt_name("") == "EMPTY"


def test_build_script_generates_aedt_operations_groups_and_boundaries():
    pins = [
        PinRecord(
            refdes="U1",
            pin_number="1",
            sym_name="SYM_A",
            comp_device="PROBE_A",
            pad_stack_name="PAD",
            pin_x=10.0,
            pin_y=20.0,
            net_name="NET/A",
        ),
        PinRecord(
            refdes="U2",
            pin_number="2",
            sym_name="SYM_A",
            comp_device="PROBE_A",
            pad_stack_name="PAD",
            pin_x=30.0,
            pin_y=40.0,
            net_name="GND",
        ),
    ]
    result = build_script(
        pins,
        GenerationOptions(project_name="Project1", design_name="HFSSDesign1", right_rotation_angle=30.0),
    )

    assert 'ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")' in result.script
    assert 'source_group_requirements = [' in result.script
    assert '"PROBE_A", "Source_PROBE_A"' in result.script
    assert 'source_groups = validate_source_groups(source_group_requirements)' in result.script
    assert 'sheet_sources = set(get_objects_in_group("Sheets"))' in result.script
    assert "duplicate_and_get_new_object" in result.script
    assert "make_unique_name" in result.script
    assert 'ensure_design_variable("CISRotAng_Right", "30")' in result.script
    assert 'ensure_design_variable("CISRotAng_Top", "270")' in result.script
    assert "DuplicateAroundAxis" in result.script
    assert "Move(" in result.script
    assert '"1", "NET/A", 10, 20, "left", "Source_PROBE_A", "CISRotAng_Left"' in result.script
    assert "Port_Group" not in result.script
    assert "AssignPerfectE" in result.script
    assert "PlacementBounds_Z0" in result.script
    assert "PlacementBounds_Z1" in result.script
    assert result.name_mappings == []
    assert result.warnings == []


def test_build_script_checks_cis_angle_variables_exist_before_declaring_variable():
    pins = [PinRecord("U1", "1", "SYM_A", "PROBE_A", "PAD", 10.0, 20.0, "NET")]

    result = build_script(pins, GenerationOptions(right_rotation_angle=45.0))

    assert "def design_variable_exists(name):" in result.script
    assert "oDesign.GetVariables()" in result.script
    assert "oDesign.GetVariableValue(name)" in result.script
    assert "if design_variable_exists(name):" in result.script
    assert '"NAME:ChangedProps"' in result.script
    assert '"NAME:NewProps"' in result.script
    assert 'ensure_design_variable("CISRotAng_Right", "45")' in result.script
    assert result.script.index("def ensure_design_variable") < result.script.index(
        'ensure_design_variable("CISRotAng_Right", "45")'
    )


def test_build_script_uses_minimum_bounding_size_for_single_point():
    pins = [
        PinRecord(
            refdes="U1",
            pin_number="1",
            sym_name="SYM_A",
            comp_device="PROBE_A",
            pad_stack_name="PAD",
            pin_x=10.0,
            pin_y=20.0,
            net_name="NET",
        )
    ]
    result = build_script(pins, GenerationOptions())

    assert "create_rectangle(placement_bounds_z0, 9.5, 19.5, 0, 1, 1)" in result.script
    assert "create_rectangle(placement_bounds_z1, 9.5, 19.5, 1, 1, 1)" in result.script
    assert result.warnings == ["Coordinate span is zero on at least one axis; applied 1mm minimum boundary size."]


def test_build_script_assigns_dgnd_sheet_clones_to_perfect_e():
    pins = [
        PinRecord(
            refdes="U1",
            pin_number="1",
            sym_name="SYM_A",
            comp_device="PROBE_A",
            pad_stack_name="PAD",
            pin_x=10.0,
            pin_y=20.0,
            net_name=" dgnd ",
        )
    ]
    result = build_script(pins, GenerationOptions())

    assert "if is_dgnd_net(net_name) and sheet_clones:" in result.script
    assert 'perf_e_name = make_unique_name("PerfE_%s" % pin_prefix, existing_boundary_names)' in result.script
    assert "assign_perfect_e(perf_e_name, sheet_clones)" in result.script
    assert "Port_Group" not in result.script


def test_build_script_does_not_create_port_group_for_non_dgnd_sheets():
    pins = [
        PinRecord(
            refdes="U1",
            pin_number="1",
            sym_name="SYM_A",
            comp_device="PROBE_A",
            pad_stack_name="PAD",
            pin_x=10.0,
            pin_y=20.0,
            net_name="SIGNAL",
        )
    ]
    result = build_script(pins, GenerationOptions())

    assert '"SIGNAL"' in result.script
    assert "Port_Group" not in result.script
    assert "if is_dgnd_net(net_name) and sheet_clones:" in result.script
