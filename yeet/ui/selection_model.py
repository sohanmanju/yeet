"""Typed rows shared by cleanup workflows and their selection engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar
from pathlib import Path

from ..models import CleanupItem

T = TypeVar("T", bound=CleanupItem)


@dataclass(frozen=True)
class SelectionState:
    selected_paths: frozenset[Path] = frozenset()
    focused_path: Path | None = None
    position: int = 0


@dataclass(frozen=True)
class SelectionRow(Generic[T]):
    index: int
    value: T
    name: str
    size: int
    group: str
    cells: Mapping[str, str]
    section: str = ""
    bulk_selectable: bool = True
    tone: str = ""
    focus_tone: str = ""


@dataclass(frozen=True)
class SectionRow:
    title: str
