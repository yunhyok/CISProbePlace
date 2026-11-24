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
    assert 'ensure_design_variable("CISRotAng_Right", "30deg")' in result.script
    assert 'ensure_design_variable("CISRotAng_Top", "90deg")' in result.script
    assert 'ensure_design_variable("CISRotAng_Bottom", "270deg")' in result.script
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
    assert 'ensure_design_variable("CISRotAng_Right", "45deg")' in result.script
    assert result.script.index("def ensure_design_variable") < result.script.index(
        'ensure_design_variable("CISRotAng_Right", "45deg")'
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


def _run_generated_script(script: str, desktop):
    import sys
    import types

    fake_env = types.ModuleType("ScriptEnv")
    fake_env.Initialize = lambda _app: None
    previous = sys.modules.get("ScriptEnv")
    sys.modules["ScriptEnv"] = fake_env
    try:
        namespace = {"oDesktop": desktop}
        exec(compile(script, "<generated>", "exec"), namespace)
        return namespace
    finally:
        if previous is None:
            sys.modules.pop("ScriptEnv", None)
        else:
            sys.modules["ScriptEnv"] = previous


class _FakeBoundaryModule:
    def __init__(self):
        self.boundaries = []

    def GetBoundaries(self):
        return list(self.boundaries)

    def AssignPerfectE(self, params):
        self.boundaries.append(params[0].split("NAME:", 1)[1])


class _FakeEditor:
    def __init__(self, groups: dict[str, list[str]], sheets: list[str] | None = None):
        self.groups = {name: list(objs) for name, objs in groups.items()}
        self.sheets = set(sheets or [])
        self.solids = {obj for objs in self.groups.values() for obj in objs} - self.sheets
        self._clone_counter = 0

    def GetObjectsInGroup(self, group_name):
        if group_name == "Solids":
            return sorted(self.solids)
        if group_name == "Sheets":
            return sorted(self.sheets)
        if group_name in ("Lines", "Points", "Unclassified"):
            return []
        return list(self.groups.get(group_name, []))

    def DuplicateAroundAxis(self, selections, *_args):
        source = selections[2]
        self._clone_counter += 1
        clone = f"{source}_clone{self._clone_counter}"
        if source in self.sheets:
            self.sheets.add(clone)
        else:
            self.solids.add(clone)

    def ChangeProperty(self, payload):
        prop_tab = payload[1]
        obj_name = prop_tab[1][1]
        change = prop_tab[2][1]
        if change[0] == "NAME:Name":
            new_name = change[2]
            if obj_name in self.solids:
                self.solids.remove(obj_name)
                self.solids.add(new_name)
            if obj_name in self.sheets:
                self.sheets.remove(obj_name)
                self.sheets.add(new_name)

    def Move(self, *_args):
        pass

    def CreateRectangle(self, _params, attrs):
        self.sheets.add(attrs[2])


class _FakeDesign:
    def __init__(self, name: str, groups: dict[str, list[str]], *, has_3d_modeler: bool = True):
        self._name = name
        self._has_3d_modeler = has_3d_modeler
        self.editor = _FakeEditor(groups)
        self.boundary = _FakeBoundaryModule()
        self.variables: dict[str, str] = {}

    def GetName(self):
        return self._name

    def SetActiveEditor(self, editor_name):
        if not self._has_3d_modeler or editor_name != "3D Modeler":
            raise RuntimeError("No 3D Modeler")
        return self.editor

    def GetModule(self, _name):
        return self.boundary

    def GetVariables(self):
        return list(self.variables)

    def GetVariableValue(self, name):
        if name not in self.variables:
            raise KeyError(name)
        return self.variables[name]

    def ChangeProperty(self, payload):
        prop = payload[1][2][1]
        name = prop[0].split("NAME:", 1)[1]
        self.variables[name] = prop[-1]


class _FakeProject:
    def __init__(self, name: str, designs: list[_FakeDesign], active_design: _FakeDesign | None = None):
        self._name = name
        self._designs = designs
        self._active = active_design
        self.set_active_calls: list[str] = []

    def GetName(self):
        return self._name

    def GetActiveDesign(self):
        return self._active

    def GetTopDesignList(self):
        return [design.GetName() for design in self._designs]

    def SetActiveDesign(self, name):
        self.set_active_calls.append(name)
        for design in self._designs:
            if design.GetName() == name:
                self._active = design
                return design
        raise RuntimeError(f"SetActiveDesign({name}) failed")


class _FakeDesktop:
    def __init__(self, projects: list[_FakeProject], active_project: _FakeProject | None = None):
        self._projects = projects
        self._active = active_project
        self.set_active_calls: list[str] = []
        self.messages: list[tuple[str, str, int, str]] = []

    def RestoreWindow(self):
        pass

    def GetActiveProject(self):
        return self._active

    def GetProjectList(self):
        return [project.GetName() for project in self._projects]

    def SetActiveProject(self, name):
        self.set_active_calls.append(name)
        matches = [project for project in self._projects if project.GetName() == name]
        if len(matches) != 1:
            raise RuntimeError(f"SetActiveProject({name}) - call failed")
        self._active = matches[0]
        return matches[0]

    def AddMessage(self, project, design, severity, text):
        self.messages.append((project, design, severity, text))


def test_generated_script_uses_active_project_and_design_when_target_blank():
    design = _FakeDesign("3J1", {"LongProbe": ["Tip"]})
    project = _FakeProject("S5K3J1_PI", [design], active_design=design)
    desktop = _FakeDesktop([project], active_project=project)
    pins = [PinRecord("", "1", "", "", "", 1.0, 2.0, "NET1", "LongProbe")]

    script = build_script(pins, GenerationOptions()).script
    namespace = _run_generated_script(script, desktop)

    assert namespace["PROJECT_NAME"] == "S5K3J1_PI"
    assert namespace["DESIGN_NAME"] == "3J1"
    assert desktop.set_active_calls == []
    assert project.set_active_calls == []
    assert "1_NET1_Tip" in design.editor.solids
    assert any(project_name == "S5K3J1_PI" and design_name == "3J1" for project_name, design_name, _, _ in desktop.messages)


def test_generated_script_skips_set_active_when_named_project_is_already_active_even_with_duplicates():
    design = _FakeDesign("3J1", {"LongProbe": ["Tip"]})
    active = _FakeProject("S5K3J1_Probe", [design], active_design=design)
    duplicate = _FakeProject("S5K3J1_Probe", [])
    desktop = _FakeDesktop([duplicate, active], active_project=active)
    pins = [PinRecord("", "1", "", "", "", 1.0, 2.0, "NET1", "LongProbe")]

    script = build_script(pins, GenerationOptions(project_name="S5K3J1_Probe.aedt", design_name="3j1")).script
    _run_generated_script(script, desktop)

    assert desktop.set_active_calls == []
    assert "1_NET1_Tip" in design.editor.solids


def test_generated_script_reports_open_projects_when_named_project_is_missing():
    import pytest

    other_design = _FakeDesign("PI_Design", {})
    other_project = _FakeProject("S5K3J1_PI", [other_design], active_design=other_design)
    desktop = _FakeDesktop([other_project], active_project=other_project)
    pins = [PinRecord("", "1", "", "", "", 1.0, 2.0, "NET1", "LongProbe")]

    script = build_script(pins, GenerationOptions(project_name="S5K3J1_Probe", design_name="3J1")).script
    with pytest.raises(Exception) as exc_info:
        _run_generated_script(script, desktop)

    message = str(exc_info.value)
    assert "S5K3J1_Probe" in message
    assert "S5K3J1_PI" in message
    assert other_design.variables == {}


def test_generated_script_validates_source_groups_before_mutating_design_variables():
    import pytest

    design = _FakeDesign("3J1", {})
    project = _FakeProject("S5K3J1_Probe", [design], active_design=design)
    desktop = _FakeDesktop([project], active_project=project)
    pins = [PinRecord("", "1", "", "", "", 1.0, 2.0, "NET1", "LongProbe")]

    script = build_script(pins, GenerationOptions()).script
    with pytest.raises(Exception, match="Missing HFSS source group LongProbe"):
        _run_generated_script(script, desktop)

    assert design.variables == {}


def test_generated_script_reports_clear_error_for_non_3d_modeler_design():
    import pytest

    design = _FakeDesign("PCB_Layout", {}, has_3d_modeler=False)
    project = _FakeProject("S5K3J1_PI", [design], active_design=design)
    desktop = _FakeDesktop([project], active_project=project)
    pins = [PinRecord("", "1", "", "", "", 1.0, 2.0, "NET1", "LongProbe")]

    script = build_script(pins, GenerationOptions()).script
    with pytest.raises(Exception, match="does not have a 3D Modeler editor"):
        _run_generated_script(script, desktop)
