from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import load_workbook

from .models import ObjectRecord, PinRecord


class DataValidationError(ValueError):
    """Raised when an input file cannot be interpreted as a supported table."""


PIN_COLUMNS = ["REFDES", "PIN_NUMBER", "SYM_NAME", "COMP_DEVICE", "PAD_STACK_NAME", "PIN_X", "PIN_Y", "NET_NAME"]
OBJECT_COLUMNS = ["category", "object_name", "object_group"]
HEADER_ALIASES = {
    "COMP_DEVICE": {"COMP_DEVICE", "COMP_DEVICE_TYPE"},
    "PIN_X": {"PIN_X", "PIX_X"},
}
VALID_CATEGORIES = {
    "object": "object",
    "port": "port",
    "perfe": "perfE",
}


def load_pin_records(path: str | Path) -> list[PinRecord]:
    rows = _read_rows(Path(path))
    header_index, indexes = _find_header(rows, PIN_COLUMNS)
    records: list[PinRecord] = []
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if _row_is_blank(row):
            continue
        values = {column: _cell_text(_get_cell(row, indexes[column])) for column in PIN_COLUMNS}
        records.append(
            PinRecord(
                refdes=values["REFDES"],
                pin_number=values["PIN_NUMBER"],
                sym_name=values["SYM_NAME"],
                comp_device=values["COMP_DEVICE"],
                pad_stack_name=values["PAD_STACK_NAME"],
                pin_x=_parse_float(values["PIN_X"], "PIN_X", row_number),
                pin_y=_parse_float(values["PIN_Y"], "PIN_Y", row_number),
                net_name=values["NET_NAME"],
            )
        )
    if not records:
        raise DataValidationError(f"No pin records found in {path}.")
    return records


def load_object_records(path: str | Path) -> list[ObjectRecord]:
    rows = _read_rows(Path(path))
    header_index, indexes = _find_header(rows, OBJECT_COLUMNS)
    records: list[ObjectRecord] = []
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if _row_is_blank(row):
            continue
        category_text = _cell_text(_get_cell(row, indexes["category"]))
        category = VALID_CATEGORIES.get(category_text.lower())
        if category is None:
            raise DataValidationError(
                f"Invalid category at row {row_number}: {category_text!r}. "
                "Allowed values are object, port, perfE."
            )
        object_name = _cell_text(_get_cell(row, indexes["object_name"]))
        if not object_name:
            raise DataValidationError(f"Missing object_name at row {row_number}.")
        object_group = _cell_text(_get_cell(row, indexes["object_group"]))
        records.append(ObjectRecord(category=category, object_name=object_name, object_group=object_group))
    if not records:
        raise DataValidationError(f"No object records found in {path}.")
    return records


def get_comp_devices(records: Iterable[PinRecord]) -> list[str]:
    return sorted({record.comp_device for record in records if record.comp_device})


def get_net_names(records: Iterable[PinRecord]) -> list[str]:
    return sorted({record.net_name for record in records if record.net_name})


def filter_pins(
    records: Iterable[PinRecord],
    *,
    comp_devices: set[str] | None = None,
    net_names: set[str] | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
) -> list[PinRecord]:
    selected: list[PinRecord] = []
    for record in records:
        if comp_devices is not None and record.comp_device not in comp_devices:
            continue
        if net_names is not None and record.net_name not in net_names:
            continue
        if x_min is not None and record.pin_x < x_min:
            continue
        if x_max is not None and record.pin_x > x_max:
            continue
        if y_min is not None and record.pin_y < y_min:
            continue
        if y_max is not None and record.pin_y > y_max:
            continue
        selected.append(record)
    return selected


def _read_rows(path: Path) -> list[list[object]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_rows(path)
    if suffix == ".xlsx":
        return _read_xlsx_rows(path)
    raise DataValidationError(f"Unsupported file format for {path}. Use .csv or .xlsx.")


def _read_csv_rows(path: Path) -> list[list[object]]:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return [row for row in csv.reader(handle)]
        except UnicodeDecodeError as exc:
            last_error = exc
    raise DataValidationError(f"Could not decode CSV file {path}: {last_error}")


def _read_xlsx_rows(path: Path) -> list[list[object]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        worksheet = workbook.active
        return [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _find_header(rows: Sequence[Sequence[object]], required_columns: Sequence[str]) -> tuple[int, dict[str, int]]:
    for row_index, row in enumerate(rows):
        normalized_to_index = {_normalize_header(cell): index for index, cell in enumerate(row) if _cell_text(cell)}
        indexes: dict[str, int] = {}
        for column in required_columns:
            match = _find_column_index(normalized_to_index, column)
            if match is not None:
                indexes[column] = match
        if len(indexes) == len(required_columns):
            return row_index, indexes
    raise DataValidationError(f"Could not find required header: {', '.join(required_columns)}.")


def _find_column_index(normalized_to_index: dict[str, int], column: str) -> int | None:
    accepted = HEADER_ALIASES.get(column, {column})
    for name in accepted:
        normalized = _normalize_header(name)
        if normalized in normalized_to_index:
            return normalized_to_index[normalized]
    return None


def _normalize_header(value: object) -> str:
    return _cell_text(value).strip().lower()


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _get_cell(row: Sequence[object], index: int) -> object:
    if index >= len(row):
        return ""
    return row[index]


def _row_is_blank(row: Sequence[object]) -> bool:
    return all(_cell_text(cell) == "" for cell in row)


def _parse_float(value: str, column: str, row_number: int) -> float:
    if value == "":
        raise DataValidationError(f"Missing {column} at row {row_number}.")
    try:
        return float(value)
    except ValueError as exc:
        raise DataValidationError(f"Invalid {column} at row {row_number}: {value!r}.") from exc
