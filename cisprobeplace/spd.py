"""Read Sigrity text SPD component pins; coordinates are returned in millimetres."""

from __future__ import annotations

import math
import re
from codecs import BOM_UTF8
from dataclasses import dataclass
from pathlib import Path

from .data_io import DataValidationError, recenter_pin_coordinates
from .models import PinRecord


_CONNECT = re.compile(r"^\.Connect\s+(\S+)\s+(\S+)", re.IGNORECASE)
_TERMINAL = re.compile(r"^\s*(\S+)\s+\$Package\.(Node[^\s!:]+)(?:!!([^\s:]+))?(?:::(\S+))?", re.IGNORECASE)
_NODE = re.compile(r"^(Node[^\s!:]+)(?:!!([^\s:]+))?(?:::(\S+))?(?:\s|$)", re.IGNORECASE)
_NODE_ID = re.compile(rb"^(Node[^\s!:]+)", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"\b(X|Y|PadStack)\s*=\s*(\S+)", re.IGNORECASE)
_DISTANCE = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Zµμ]+)")
_TO_MM = {
    "nm": 1e-6, "um": 0.001, "μm": 0.001, "mm": 1.0, "cm": 10.0,
    "m": 1000.0, "mil": 0.0254, "in": 25.4, "inch": 25.4,
}
_SITE = re.compile(r"/(\d+)$")
_SITE_PREFIX = re.compile(r"^U(\d+)_", re.IGNORECASE)
_SITE_INSTANCE = re.compile(r"SITE(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class SpdData:
    """Component/model inventory with independent, centred physical site selections."""

    _records: dict[str, dict[int | None, list[PinRecord]]]

    @property
    def components(self) -> tuple[str, ...]:
        return tuple(sorted(self._records, key=str.casefold))

    def sites(self, component: str) -> tuple[int | None, ...]:
        groups = self._component(component)
        numbered = sorted(site for site in groups if site is not None)
        return tuple([*numbered, None] if None in groups else numbered)

    def pins(self, component: str, site: int | None) -> list[PinRecord]:
        groups = self._component(component)
        if site not in groups:
            raise DataValidationError(f"SPD component {component!r} has no site {site!r}.")
        return recenter_pin_coordinates(list(groups[site]))

    def _component(self, component: str) -> dict[int | None, list[PinRecord]]:
        if component not in self._records:
            raise DataValidationError(f"Unknown SPD component: {component!r}.")
        return self._records[component]


def read_spd(path: str | Path) -> SpdData:
    """Scan connections first, then read only their physical Node records.

    Board shapes, traces and vias are never retained. All selections subsequently
    use memory, so switching a site does not reopen a potentially gigabyte file.
    """
    path = Path(path)
    try:
        with path.open("rb") as handle:
            header = handle.read(256)
            if b"\x00" in header:
                raise DataValidationError("SPD must be a text file, not binary or UTF-16.")
            offset = len(BOM_UTF8) if header.startswith(BOM_UTF8) else 0
            handle.seek(offset)
            connections: list[tuple[str, str, str, str, str, str]] = []
            instance: tuple[str, str] | None = None
            node_start: int | None = None
            for line_number, raw in enumerate(handle, start=1):
                stripped = raw.lstrip()
                lower = stripped.lower()
                if node_start is None:
                    if lower.startswith(b"node") and _NODE_ID.match(stripped):
                        node_start = offset
                    offset += len(raw)
                if lower.startswith(b"*"):
                    # A comment line. A pin connection that was commented out must
                    # be skipped, not read as a pin (or rejected as malformed).
                    continue
                if lower.startswith((b".connect ", b".connect\t")):
                    match = _CONNECT.match(_decode(stripped))
                    if not match:
                        raise DataValidationError(f"Malformed SPD .Connect header at line {line_number}.")
                    instance = match.group(1), match.group(2)
                elif lower.startswith(b"."):
                    instance = None
                elif instance is not None and b"$package.node" in lower:
                    match = _TERMINAL.match(_decode(stripped))
                    if not match:
                        raise DataValidationError(
                            f"Malformed SPD pin connection for {instance[0]!r} at line {line_number}."
                        )
                    pin, node, physical_pin, net = match.groups()
                    connections.append((*instance, pin, node.casefold(), physical_pin or "", net or ""))
            if not connections or node_start is None:
                raise DataValidationError(f"No component pin coordinates found in SPD file {path.name}.")

            needed = {entry[3] for entry in connections}
            nodes: dict[str, tuple[str, str, float, float, str]] = {}
            handle.seek(node_start)
            pending: str | None = None
            for raw in handle:
                stripped = raw.lstrip()
                if pending is not None and stripped.startswith(b"+"):
                    pending += " " + _decode(stripped[1:]).strip()
                    continue
                if pending is not None:
                    _store_node(pending, nodes)
                    pending = None
                if stripped.lower().startswith(b".endpackage"):
                    break
                if stripped.lower().startswith(b"node"):
                    match = _NODE_ID.match(stripped)
                    if match and _decode(match.group(1)).casefold() in needed:
                        pending = _decode(stripped).strip()
            if pending is not None:
                _store_node(pending, nodes)
    except OSError as exc:
        raise DataValidationError(f"Could not read SPD file {path}: {exc}") from exc

    records: dict[str, dict[int | None, list[PinRecord]]] = {}
    for refdes, component, pin, node, physical_pin, connection_net in connections:
        if node not in nodes:
            raise DataValidationError(f"SPD pin {refdes}.{pin} refers to a missing physical node.")
        node_pin, node_net, x, y, pad = nodes[node]
        net = node_net or connection_net
        site = _site_number(refdes, instance=True)
        if site is None:
            site = _site_number(net)
        if site is None:
            site = _site_number(pin)
        if site is None:
            site = _site_number(node_pin or physical_pin)
        record = PinRecord(
            refdes=refdes, pin_number=pin, sym_name=component, comp_device="",
            pad_stack_name=pad, pin_x=x, pin_y=y, net_name=net,
        )
        records.setdefault(component, {}).setdefault(site, []).append(record)
    return SpdData(records)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp949")
        except UnicodeDecodeError as exc:
            raise DataValidationError("Could not decode SPD pin data as UTF-8 or CP949.") from exc


def _store_node(line: str, nodes: dict[str, tuple[str, str, float, float, str]]) -> None:
    match = _NODE.match(line)
    if match is None:
        raise DataValidationError(f"Malformed SPD physical node record: {line[:60]!r}.")
    node, pin, net = match.groups()
    attributes = {name.casefold(): value for name, value in _ATTRIBUTE.findall(line)}
    if "x" not in attributes or "y" not in attributes:
        raise DataValidationError(f"Missing SPD X/Y coordinate for {node}.")
    values = (pin or "", net or "", _distance_mm(attributes["x"], node),
              _distance_mm(attributes["y"], node), attributes.get("padstack", ""))
    key = node.casefold()
    if key in nodes and nodes[key] != values:
        raise DataValidationError(f"Conflicting SPD physical node: {node}.")
    nodes[key] = values


def _distance_mm(text: str, node: str) -> float:
    match = _DISTANCE.fullmatch(text)
    if match is None or match.group(2).casefold() not in _TO_MM:
        raise DataValidationError(f"Invalid or unsupported SPD coordinate unit for {node}: {text!r}.")
    value = float(match.group(1)) * _TO_MM[match.group(2).casefold()]
    if not math.isfinite(value):
        raise DataValidationError(f"SPD coordinate for {node} must be finite: {text!r}.")
    return value


def _site_number(text: str, *, instance: bool = False) -> int | None:
    match = (_SITE_INSTANCE.fullmatch(text) if instance else None) or _SITE.search(text)
    if match is None and not instance:
        match = _SITE_PREFIX.match(text)
    return int(match.group(1)) if match else None
