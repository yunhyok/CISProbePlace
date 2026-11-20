from pathlib import Path

import pytest

from cisprobeplace.data_io import DataValidationError, filter_pins, get_comp_devices, get_net_names, load_object_records, load_pin_records
from cisprobeplace.models import PinRecord


def test_load_pin_records_finds_late_header_alias_and_null_values(tmp_path: Path):
    path = tmp_path / "pins.csv"
    path.write_text(
        "Allegro symbol pin report\n"
        "generated,metadata\n"
        "REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIX_X,PIN_Y,NET_NAME\n"
        "U1,1,SYM_A,PROBE_A,PAD,10.5,20.25,NET/A\n"
        "U2,2,SYM_B,PROBE_B,,11,21,\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    assert len(records) == 2
    assert records[0].pin_x == -0.25
    assert records[0].pin_y == -0.375
    assert records[0].net_name == "NET/A"
    assert records[1].pad_stack_name == ""
    assert records[1].net_name == ""
    assert get_comp_devices(records) == ["PROBE_A", "PROBE_B"]


def test_load_pin_records_reads_xlsx_with_header_not_on_first_row(tmp_path: Path):
    from openpyxl import Workbook

    path = tmp_path / "pins.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["ignored"])
    ws.append(["REFDES", "PIN_NUMBER", "SYM_NAME", "COMP_DEVICE", "PAD_STACK_NAME", "PIN_X", "PIN_Y", "NET_NAME"])
    ws.append(["U3", "A1", "SYM_C", "PROBE_C", "PAD_C", 1.25, 2.5, "VDD"])
    wb.save(path)

    records = load_pin_records(path)

    assert len(records) == 1
    assert records[0].pin_number == "A1"
    assert records[0].comp_device == "PROBE_C"
    assert records[0].pin_x == 0.0
    assert records[0].pin_y == 0.0




def test_load_pin_records_reads_coordinate_schema_with_source_probe_name(tmp_path: Path):
    path = tmp_path / "cis_coordinates.csv"
    path.write_text(
        "metadata\n"
        "X\uc88c\ud45c,Y\uc88c\ud45c,Net Name,Source_probe name\n"
        "10,5,SIGNAL_A,LongProbe\n"
        "5,10,DGND,ShortProbe\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    assert len(records) == 2
    assert records[0].pin_x == 2.5
    assert records[0].pin_y == -2.5
    assert records[0].net_name == "SIGNAL_A"
    assert records[0].source_probe_name == "LongProbe"
    assert records[0].comp_device == ""
    assert records[1].source_probe_name == "ShortProbe"


def test_load_pin_records_coordinate_schema_defaults_missing_source_probe_name(tmp_path: Path):
    path = tmp_path / "one_probe.csv"
    path.write_text(
        "X,Y,NET\n"
        "0,0,SIGNAL_A\n"
        "10,0,DGND\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    assert [record.source_probe_name for record in records] == ["", ""]
    assert [record.net_name for record in records] == ["SIGNAL_A", "DGND"]


def test_load_pin_records_reads_unlabeled_fourth_coordinate_column_as_source_probe_name(tmp_path: Path):
    from openpyxl import Workbook

    path = tmp_path / "coord.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["PIN_X", "PIN_Y", "NET_NAME", None])
    ws.append([44.0044, 42.9169, "U1_VNTG", "Source_CLS35SE_SBP"])
    ws.append([43.9045, 42.1669, "DGND", "Source_CLS35S_SBP"])
    wb.save(path)

    records = load_pin_records(path)

    assert [record.source_probe_name for record in records] == ["Source_CLS35SE_SBP", "Source_CLS35S_SBP"]
    assert [record.net_name for record in records] == ["U1_VNTG", "DGND"]


def test_load_pin_records_recenters_coordinate_bbox_to_origin(tmp_path: Path):
    path = tmp_path / "far_coordinates.csv"
    path.write_text(
        "X,Y,NET,Source_probe name\n"
        "1000,2000,N1,LongProbe\n"
        "1020,2060,N2,ShortProbe\n"
        "1010,2030,DGND,ShortProbe\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    assert [(record.pin_x, record.pin_y) for record in records] == [(-10.0, -30.0), (10.0, 30.0), (0.0, 0.0)]
    assert [record.source_probe_name for record in records] == ["LongProbe", "ShortProbe", "ShortProbe"]


def test_load_pin_records_recenters_allegro_bbox_to_origin(tmp_path: Path):
    path = tmp_path / "far_allegro.csv"
    path.write_text(
        "REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME\n"
        "U1,1,SYM_A,PROBE_A,PAD,5000,7000,N1\n"
        "U1,2,SYM_A,PROBE_A,PAD,5020,7060,N2\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    assert [(record.pin_x, record.pin_y) for record in records] == [(-10.0, -30.0), (10.0, 30.0)]
    assert [record.comp_device for record in records] == ["PROBE_A", "PROBE_A"]

def test_load_pin_records_accepts_allegro_comp_device_type_header(tmp_path: Path):
    from openpyxl import Workbook

    path = tmp_path / "synthetic_allegro.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Synthetic component pin report"])
    sheet.append(["Fictional component data"])
    sheet.append(["REFDES", "PIN_NUMBER", "SYM_NAME", "COMP_DEVICE_TYPE", "PAD_STACK_NAME", "PIN_X", "PIN_Y", "NET_NAME"])
    sheet.append(["U_DEMO", 1, "SYM_DEMO", "PROBE_DEMO", "PAD_DEMO", 1.25, -2.5, "NET_DEMO"])
    workbook.save(path)

    pins = load_pin_records(path)

    assert len(pins) == 1
    assert pins[0].refdes == "U_DEMO"
    assert pins[0].pin_number == "1"
    assert pins[0].comp_device == "PROBE_DEMO"
    assert pins[0].net_name == "NET_DEMO"


def test_load_object_records_requires_valid_category(tmp_path: Path):
    path = tmp_path / "objects.csv"
    path.write_text(
        "category,object_name,object_group\n"
        "object,Body,Probe\n"
        "bad,Top,Probe\n",
        encoding="utf-8",
    )

    with pytest.raises(DataValidationError, match="category"):
        load_object_records(path)


def test_filter_pins_by_multiple_devices_and_coordinate_bounds(tmp_path: Path):
    path = tmp_path / "pins.csv"
    path.write_text(
        "REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME\n"
        "U1,1,SYM_A,PROBE_A,PAD,0,0,N1\n"
        "U2,2,SYM_B,PROBE_B,PAD,5,5,N2\n"
        "U3,3,SYM_C,PROBE_C,PAD,9,9,N3\n",
        encoding="utf-8",
    )
    records = load_pin_records(path)

    selected = filter_pins(records, comp_devices={"PROBE_A", "PROBE_B"}, x_min=-1, x_max=1, y_min=-1, y_max=1)

    assert [record.pin_number for record in selected] == ["2"]


def test_filter_pins_by_net_names(tmp_path: Path):
    path = tmp_path / "pins.csv"
    path.write_text(
        "REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME\n"
        "U1,1,SYM_A,PROBE_A,PAD,0,0,DGND\n"
        "U2,2,SYM_B,PROBE_A,PAD,5,5,SIGNAL_A\n"
        "U3,3,SYM_C,PROBE_A,PAD,9,9,SIGNAL_B\n",
        encoding="utf-8",
    )
    records = load_pin_records(path)

    selected = filter_pins(records, comp_devices={"PROBE_A"}, net_names={"DGND", "SIGNAL_B"})

    assert get_net_names(records) == ["DGND", "SIGNAL_A", "SIGNAL_B"]
    assert [record.pin_number for record in selected] == ["1", "3"]


def test_filter_pins_includes_values_on_rounded_coordinate_bounds():
    records = [
        # Recentered spreadsheet values can be a few floating-point ulps outside
        # the six-decimal GUI spinbox display value.
        PinRecord("", "1", "", "", "", -3.6766000000000005, 0.0, "N1"),
        PinRecord("", "2", "", "", "", 3.6766000000000076, 0.0, "N2"),
        PinRecord("", "3", "", "", "", 0.0, -3.8819000000000017, "N3"),
    ]

    selected = filter_pins(records, x_min=-3.6766, x_max=3.6766, y_min=-3.8819, y_max=3.8819)

    assert [record.pin_number for record in selected] == ["1", "2", "3"]


def test_filter_pins_empty_checked_sets_select_no_rows(tmp_path: Path):
    path = tmp_path / "pins.csv"
    path.write_text(
        "REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME\n"
        "U1,1,SYM_A,PROBE_A,PAD,0,0,DGND\n",
        encoding="utf-8",
    )
    records = load_pin_records(path)

    assert filter_pins(records, comp_devices=set()) == []
    assert filter_pins(records, net_names=set()) == []


def test_load_pin_records_prefers_first_listed_alias_when_several_are_present(tmp_path: Path):
    path = tmp_path / "duplicate_aliases.csv"
    path.write_text(
        "PIN_X,X,PIN_Y,Y,NET_NAME,NET\n"
        "100,1,200,2,ALLEGRO_A,COORD_A\n"
        "300,3,400,4,ALLEGRO_B,COORD_B\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    # X / Y / NET are listed ahead of PIN_X / PIN_Y, and NET_NAME ahead of NET.
    assert [(record.pin_x, record.pin_y) for record in records] == [(-1.0, -1.0), (1.0, 1.0)]
    assert [record.net_name for record in records] == ["ALLEGRO_A", "ALLEGRO_B"]


def test_load_pin_records_reads_unlabeled_fourth_csv_column_when_header_row_is_shorter(tmp_path: Path):
    path = tmp_path / "short_header.csv"
    path.write_text(
        "PIN_X,PIN_Y,NET_NAME\n"
        "1,2,N1,LongProbe\n"
        "3,4,N2,ShortProbe\n",
        encoding="utf-8",
    )

    records = load_pin_records(path)

    assert [record.source_probe_name for record in records] == ["LongProbe", "ShortProbe"]


@pytest.mark.parametrize("bad_value", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_load_pin_records_rejects_non_finite_coordinates(tmp_path: Path, bad_value: str):
    path = tmp_path / "non_finite.csv"
    path.write_text(
        "X,Y,NET\n"
        "1,2,N1\n"
        f"{bad_value},4,N2\n",
        encoding="utf-8",
    )

    with pytest.raises(DataValidationError, match="row 3"):
        load_pin_records(path)


def test_load_pin_records_reads_xlsx_with_wrong_dimension_record(tmp_path: Path):
    import re
    import zipfile

    from openpyxl import Workbook

    source = tmp_path / "source.xlsx"
    path = tmp_path / "wrong_dimension.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["X", "Y", "NET", "Source_probe name"])
    ws.append([10, 5, "SIGNAL_A", "LongProbe"])
    ws.append([5, 10, "DGND", "ShortProbe"])
    wb.save(source)
    # Some exporters store a dimension of "A1" no matter how large the sheet is.
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as patched:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                assert "<dimension" in text
                data = re.sub(r'<dimension ref="[^"]*"', '<dimension ref="A1"', text).encode("utf-8")
            patched.writestr(item, data)

    records = load_pin_records(path)

    assert [record.net_name for record in records] == ["SIGNAL_A", "DGND"]
    assert [record.source_probe_name for record in records] == ["LongProbe", "ShortProbe"]
