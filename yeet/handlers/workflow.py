"""Contracts between scanner adapters and cleanup navigation."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from ..models import CleanupItem

T = TypeVar("T", bound=CleanupItem)


class RootPolicy(Enum):
    DIRECTORY = "directory"
    DEFAULT_LOCATIONS = "default_locations"
    SYSTEM = "system"

    @property
    def accepts_directory(self) -> bool:
        return self is not RootPolicy.SYSTEM


class ScanProgress(Protocol):
    def __call__(self, count: int, detail: str | int, name: str = "") -> None: ...


@dataclass(frozen=True)
class ScanBatch(Generic[T]):
    items: list[T]
    scanned_count: int
    errors: list[str]
    payload: dict[str, object]
    review_notes: dict[Path, str] = field(default_factory=dict)
