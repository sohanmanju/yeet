"""Project markers and traversal exclusions."""

from __future__ import annotations
from fnmatch import fnmatch
from .models import ProjectType

SKIP_FOR_SIZE = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "env",
        "target",
        "build",
        "dist",
        ".next",
        ".nuxt",
        "vendor",
        "Pods",
        ".gradle",
    }
)

# Detection preserves the existing precedence and Git-only requirements rule.
TYPED_PROJECT_MARKERS = (
    (ProjectType.NODE, frozenset({"package.json"})),
    (ProjectType.PYTHON, frozenset({"pyproject.toml", "setup.py"})),
    (ProjectType.RUST, frozenset({"Cargo.toml"})),
    (ProjectType.GO, frozenset({"go.mod"})),
)
OTHER_PROJECT_MARKERS = frozenset(
    {
        "Gemfile",
        "pom.xml",
        "build.gradle",
        "composer.json",
        "pubspec.yaml",
    }
)

GIT_ONLY_PYTHON_MARKERS = frozenset({"requirements.txt"})
XCODE_PROJECT_SUFFIXES = (".xcodeproj", ".xcworkspace")
OWNERSHIP_ONLY_MARKERS = frozenset(
    {
        "Pipfile",
        "build.gradle.kts",
        "*.csproj",
        "*.sln",
        "Package.swift",
    }
)

PROJECT_MARKERS = frozenset().union(
    *(markers for _, markers in TYPED_PROJECT_MARKERS),
    OTHER_PROJECT_MARKERS,
    GIT_ONLY_PYTHON_MARKERS,
    OWNERSHIP_ONLY_MARKERS,
    {".git"},
    {"*" + suffix for suffix in XCODE_PROJECT_SUFFIXES},
)


def detect_project_type(entries: set[str]) -> ProjectType | None:
    is_git = ".git" in entries
    for project_type, markers in TYPED_PROJECT_MARKERS:
        if entries & markers or (
            project_type is ProjectType.PYTHON
            and is_git
            and entries & GIT_ONLY_PYTHON_MARKERS
        ):
            return project_type
    if is_git:
        return ProjectType.GIT
    if entries & OTHER_PROJECT_MARKERS or any(
        name.endswith(XCODE_PROJECT_SUFFIXES) for name in entries
    ):
        return ProjectType.OTHER
    return None


def contains_project_marker(entries: set[str]) -> bool:
    """Artifact ownership recognizes the broader set of declared project formats."""
    return any(fnmatch(name, marker) for marker in PROJECT_MARKERS for name in entries)
