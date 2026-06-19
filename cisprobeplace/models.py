from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PinRecord:
    refdes: str
    pin_number: str
    sym_name: str
    comp_device: str
    pad_stack_name: str
    pin_x: float
    pin_y: float
    net_name: str


@dataclass(frozen=True)
class ObjectRecord:
    category: str
    object_name: str
    object_group: str = ""


@dataclass(frozen=True)
class GenerationOptions:
    project_name: str = "Project1"
    design_name: str = "HFSSDesign1"
    right_rotation_angle: float = 0.0
    top_rotation_angle: float = 270.0
    left_rotation_angle: float = 180.0
    bottom_rotation_angle: float = 90.0


@dataclass(frozen=True)
class NameMapping:
    original: str
    generated: str


@dataclass(frozen=True)
class GenerationResult:
    script: str
    name_mappings: list[NameMapping] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
