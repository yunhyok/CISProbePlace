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
        self.group_parents: dict[str, str] = {name: "Model" for name in self.groups}
        self.object_groups: dict[str, str] = {
            obj: name for name, objs in self.groups.items() for obj in objs
        }
        self.sheets = set(sheets or [])
        self.solids = {obj for objs in self.groups.values() for obj in objs} - self.sheets
        self._clone_counter = 0
        self._group_counter = 0

    def GetChildNames(self, category=None):
        if category == "Groups":
            return sorted(self.groups)
        return []

    def GetObjectsInGroup(self, group_name):
        if group_name == "Solids":
            return sorted(self.solids)
        if group_name == "Sheets":
            return sorted(self.sheets)
        if group_name in ("Lines", "Points", "Unclassified"):
            return []
        return list(self.groups.get(group_name, []))

    def GetPropertyValue(self, _tab, obj_name, prop_name):
        if prop_name == "Group":
            return self.object_groups.get(obj_name, "Model")
        return ""

    def DuplicateAroundAxis(self, selections, *_args):
        source = selections[2]
        self._clone_counter += 1
        clone = f"{source}_clone{self._clone_counter}"
        if source in self.sheets:
            self.sheets.add(clone)
        else:
            self.solids.add(clone)
        # Mirror HFSS: cloned object initially stays in the source object's group.
        source_group = self.object_groups.get(source, "Model")
        self.object_groups[clone] = source_group
        if source_group in self.groups:
            self.groups[source_group].append(clone)

    def _move_object(self, obj_name: str, target_group: str):
        old_group = self.object_groups.get(obj_name, "Model")
        if old_group in self.groups and obj_name in self.groups[old_group]:
            self.groups[old_group].remove(obj_name)
        self.object_groups[obj_name] = target_group
        if target_group in self.groups and obj_name not in self.groups[target_group]:
            self.groups[target_group].append(obj_name)

    def CreateGroup(self, params):
        parent_id = params[2]
        parts_text = params[4]
        parts = [part for part in parts_text.split(",") if part]
        self._group_counter += 1
        assigned = f"Group{self._group_counter}"
        self.groups[assigned] = []
        self.group_parents[assigned] = parent_id
        for part in parts:
            self._move_object(part, assigned)
        return assigned

    def MoveEntityToGroup(self, items, parent_spec):
        parent_group = parent_spec[1]
        if items[0] == "Objects:=":
            for obj_name in items[1]:
                self._move_object(obj_name, parent_group)
        elif items[0] == "Groups:=":
            for group_name in items[1]:
                self.group_parents[group_name] = parent_group

    def ChangeProperty(self, payload):
        prop_tab = payload[1]
        tab_name = prop_tab[0]
        target_name = prop_tab[1][1]
        change = prop_tab[2][1]
        if tab_name == "NAME:Attributes" and change[0] == "NAME:Name":
            new_name = change[2]
            self.groups[new_name] = self.groups.pop(target_name)
            self.group_parents[new_name] = self.group_parents.pop(target_name)
            for child, parent in list(self.group_parents.items()):
                if parent == target_name:
                    self.group_parents[child] = new_name
            for obj_name, group in list(self.object_groups.items()):
                if group == target_name:
                    self.object_groups[obj_name] = new_name
        elif change[0] == "NAME:Name":
            new_name = change[2]
            if target_name in self.solids:
                self.solids.remove(target_name)
                self.solids.add(new_name)
            if target_name in self.sheets:
                self.sheets.remove(target_name)
                self.sheets.add(new_name)
            old_group = self.object_groups.pop(target_name, "Model")
            self.object_groups[new_name] = old_group
            if old_group in self.groups and target_name in self.groups[old_group]:
                self.groups[old_group][self.groups[old_group].index(target_name)] = new_name
        elif change[0] == "NAME:Group":
            self._move_object(target_name, change[2])

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


def test_generated_script_creates_top_level_generated_group_with_per_net_subgroups():
    design = _FakeDesign("3J1", {"LongProbe": ["LongTip"], "ShortProbe": ["ShortTip"]})
    project = _FakeProject("S5K3J1_Probe", [design], active_design=design)
    desktop = _FakeDesktop([project], active_project=project)
    pins = [
        PinRecord("", "1", "", "", "", -3.0, 1.0, "DGND", "LongProbe"),
        PinRecord("", "2", "", "", "", -2.0, 1.0, "DGND", "ShortProbe"),
        PinRecord("", "3", "", "", "", 0.0, 3.0, "U1_VDDA", "LongProbe"),
        PinRecord("", "4", "", "", "", 1.0, 3.0, "NET/A", "ShortProbe"),
    ]

    script = build_script(pins, GenerationOptions()).script
    _run_generated_script(script, desktop)

    editor = design.editor
    assert editor.group_parents["Generated_Group"] == "Model"
    assert editor.group_parents["DGND"] == "Generated_Group"
    assert editor.group_parents["U1_VDDA"] == "Generated_Group"
    assert editor.group_parents["NET_A"] == "Generated_Group"
    assert set(editor.groups["DGND"]) == {"1_DGND_LongTip", "2_DGND_ShortTip"}
    assert editor.groups["U1_VDDA"] == ["3_U1_VDDA_LongTip"]
    assert editor.groups["NET_A"] == ["4_NET_A_ShortTip"]
    # Source groups remain untouched and contain only original source objects.
    assert editor.groups["LongProbe"] == ["LongTip"]
    assert editor.groups["ShortProbe"] == ["ShortTip"]
