from pathlib import Path

import pytest

from cisprobeplace.data_io import DataValidationError
from cisprobeplace.spd import read_spd


def write_spd(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "synthetic.spd"
    path.write_text(text, encoding="utf-8")
    return path


def test_groups_instances_by_part_and_centres_only_selected_site(tmp_path: Path):
    path = write_spd(tmp_path, """.Package $Package
Node1!!A1::NET/10 X = 10000um Y = 20mm Layer = TOP PadStack = PAD_A
Node2!!A2::DGND X = 12mm Y = 24mm PadStack = PAD_B
Node3!!B1::NET/2 X = -10mm Y = -20mm PadStack = PAD_C
Node4!!B2::DGND X = -12mm Y = -24mm PadStack = PAD_D
Node999::BOARD_NET X = bad Y = bad
.EndPackage
.Connect SITE10 DUT Usage = 0b1000
A1 $Package.Node1!!A1::NET/10
A2 $Package.Node2!!A2::DGND
.EndC
.Connect SITE2 DUT
B1 $Package.Node3!!B1::NET/2
B2 $Package.Node4!!B2::DGND
.EndC
.Part DUT Outline = 1mm 1mm
""")
    data = read_spd(path)
    path.unlink()  # Site switches must never reopen the original file.
    assert data.components == ("DUT",)
    assert data.sites("DUT") == (2, 10)
    pins = data.pins("DUT", 10)
    assert [(p.pin_x, p.pin_y) for p in pins] == [(-1, -2), (1, 2)]
    assert [p.net_name for p in pins] == ["NET/10", "DGND"]
    assert [p.refdes for p in pins] == ["SITE10", "SITE10"]
    assert pins[0].sym_name == "DUT"
    assert pins[0].comp_device == pins[0].source_probe_name == ""
    assert pins[0].pin_number == "A1"
    assert pins[0].pad_stack_name == "PAD_A"
    assert [(p.pin_x, p.pin_y) for p in data.pins("DUT", 2)] == [(1, 2), (-1, -2)]


def test_net_and_pin_site_fallback_keeps_unassigned_separate(tmp_path: Path):
    data = read_spd(write_spd(tmp_path, """Node1!!A1::signal/1 X = 1mm Y = 2mm
Node2!!A2::Un_NET X = 100mm Y = 200mm
Node3!!pin/0::Un_NET X = 3mm Y = 4mm
Node4!!A4 X = 5mm Y = 6mm
Node5!!A5::DGND X = 7mm Y = 8mm
.Connect U1 TEST_PART
A1 $Package.Node1!!A1::signal/1
A2 $Package.Node2!!A2::Un_NET
A3 $Package.Node3!!pin/0::Un_NET
A4 $Package.Node4!!A4::saved_original_net
.EndC
.Connect U2/3 TEST_PART
A5 $Package.Node5!!A5::DGND
.EndC
"""))
    assert data.sites("TEST_PART") == (0, 1, 3, None)
    assert [pin.net_name for pin in data.pins("TEST_PART", 0)] == ["Un_NET"]
    assert [pin.net_name for pin in data.pins("TEST_PART", None)] == ["Un_NET", "saved_original_net"]
    assert [pin.refdes for pin in data.pins("TEST_PART", 3)] == ["U2/3"]
    with pytest.raises(DataValidationError, match="Unknown SPD component"):
        data.pins("UNKNOWN", None)
    with pytest.raises(DataValidationError, match="has no site"):
        data.pins("TEST_PART", 99)


@pytest.mark.parametrize("unit,value", [("um", 1000), ("nm", 1000000), ("mm", 1), ("cm", .1),
                                         ("m", .001), ("mil", 1 / .0254), ("in", 1 / 25.4), ("µm", 1000)])
def test_converts_explicit_units_to_mm(tmp_path: Path, unit: str, value: float):
    data = read_spd(write_spd(tmp_path, f"""Node1!!1::NET/0 X = 0mm Y = 0mm
Node2!!2::NET/0 X = {value:.15g}{unit} Y = 2mm
.Connect U1 P
1 $Package.Node1!!1::NET/0
2 $Package.Node2!!2::NET/0
.EndC
"""))
    assert data.pins("P", 0)[1].pin_x == pytest.approx(.5)


def test_reads_continued_node_attributes(tmp_path: Path):
    data = read_spd(write_spd(tmp_path, """Node1!!1::NET/0 X = 1mm
+ Y = 2mm PadStack = CONTINUED
.EndPackage
.Connect SITE0 P
1 $Package.Node1!!1::NET/0
.EndC
"""))
    assert data.pins("P", 0)[0].pad_stack_name == "CONTINUED"


def test_preserves_cp949_node_and_net_names(tmp_path: Path):
    path = tmp_path / "cp949.spd"
    path.write_bytes(
        "Node핀!!1::U1_신호 X = 1mm Y = 2mm\n.Connect U1 DUT\n1 $Package.Node핀!!1::U1_신호\n.EndC\n".encode("cp949")
    )
    assert read_spd(path).pins("DUT", 1)[0].net_name == "U1_신호"


def test_u_number_net_and_pin_prefixes_do_not_infer_instance_underscore_suffix(tmp_path: Path):
    data = read_spd(write_spd(tmp_path, """Node1!!1::U3_CLK X = 0mm Y = 0mm
Node2!!A2::DGND X = 1mm Y = 1mm
Node3!!3::DGND X = 2mm Y = 2mm
.Connect U1_0 P
1 $Package.Node1!!1::U3_CLK
U2_DATA $Package.Node2!!A2::DGND
3 $Package.Node3!!3::DGND
.EndC
"""))
    assert data.sites("P") == (2, 3, None)
    assert data.pins("P", 3)[0].net_name == "U3_CLK"
    assert data.pins("P", 2)[0].net_name == "DGND"


@pytest.mark.parametrize("node", ["X = 1 Y = 2mm", "X = 1parsec Y = 2mm", "X = nanmm Y = 2mm",
                                    "X = 1e999mm Y = 2mm", "X = 1mm", "X = garbage Y = 2mm"])
def test_rejects_invalid_or_ambiguous_coordinates(tmp_path: Path, node: str):
    with pytest.raises(DataValidationError):
        read_spd(write_spd(tmp_path, f"Node1!!1::NET/0 {node}\n.Connect U1 P\n1 $Package.Node1!!1::NET/0\n.EndC\n"))


def test_rejects_missing_physical_node_and_non_spd_file(tmp_path: Path):
    for text in ("not an SPD", "Node1!!1 X = 1mm Y = 2mm\n.Connect U1 P\n1 $Package.Node2!!1\n.EndC\n", "binary\x00data"):
        with pytest.raises(DataValidationError):
            read_spd(write_spd(tmp_path, text))
    with pytest.raises(DataValidationError, match="Could not read SPD"):
        read_spd(tmp_path / "missing.spd")


def test_rejects_conflicting_duplicate_node(tmp_path: Path):
    with pytest.raises(DataValidationError, match="Conflicting"):
        read_spd(write_spd(tmp_path, """Node1!!1 X = 1mm Y = 2mm
Node1!!1 X = 3mm Y = 4mm
.Connect U1 P
1 $Package.Node1!!1
.EndC
"""))


def test_initial_utf8_bom(tmp_path: Path):
    data = read_spd(write_spd(tmp_path, "\ufeffNode1!!1::U10_GND X = 1mm Y = 2mm\n.Connect U1 P\n1 $Package.Node1!!1::U10_GND\n.EndC\n"))
    assert data.sites("P") == (10,)
    assert data.pins("P", 10)[0].net_name == "U10_GND"


@pytest.mark.parametrize("net", ["AU3_CLK", "U_CLK", "U-3_CLK", "signal/3extra", "signal/-3", "Un_NET"])
def test_site_markers_are_strict(tmp_path: Path, net: str):
    data = read_spd(write_spd(tmp_path, f"Node1!!1::{net} X = 0mm Y = 0mm\n.Connect U1 P\n1 $Package.Node1!!1::{net}\n.EndC\n"))
    assert data.sites("P") == (None,)


def test_comment_lines_are_not_read_as_pins_or_nodes(tmp_path: Path):
    data = read_spd(write_spd(tmp_path, """* Node9!!Z9::OLD/3 X = 99mm Y = 99mm
Node1!!A1::CLK/3 X = 1mm Y = 2mm
Node2!!A2::DGND X = 3mm Y = 4mm
.Connect SITE3 DUT
* [REM] A9 $Package.Node2!!A2::DGND was removed from this site
A1 $Package.Node1!!A1::CLK/3
*A2 $Package.Node2!!A2::DGND
.EndC
"""))
    # A commented-out connection used to abort the whole file as malformed.
    assert [(pin.pin_number, pin.net_name) for pin in data.pins("DUT", 3)] == [("A1", "CLK/3")]


def test_errors_name_the_line_or_node_to_look_at(tmp_path: Path):
    node = "Node1!!A1::CLK/3 X = 1mm Y = 2mm\n"
    with pytest.raises(DataValidationError, match=r"pin connection for 'SITE3' at line 4\."):
        read_spd(write_spd(tmp_path, node + "\n.Connect SITE3 DUT\nA1 extra $Package.Node1\n.EndC\n"))
    with pytest.raises(DataValidationError, match=r"\.Connect header at line 2\."):
        read_spd(write_spd(tmp_path, node + ".Connect \tSITE3\n.EndC\n"))
    with pytest.raises(DataValidationError, match=r"coordinate unit for Node7: '1\.5e-3'"):
        read_spd(write_spd(tmp_path, "Node7!!A1::CLK/3 X = 1.5e-3 Y = 2mm\n.Connect SITE3 DUT\nA1 $Package.Node7\n.EndC\n"))
