"""Workflow-specific columns, independent of sizing and selection behavior."""

from .responsive import Column, TableSchema

PROJECTS = TableSchema(
    (
        Column("select", "", 3),
        Column("num", "#", 4, "right", 30),
        Column("name", "Project", 12, grow=3),
        Column("type", "Type", 7, priority=40),
        Column("size", "Size", 10, "right"),
        Column("opened", "Last Opened", 13, "right", 20),
        Column("commit", "Last Commit", 13, "right", 10),
    ),
    marker_width=2,
)

FILES = TableSchema(
    (
        Column("select", "", 3),
        Column("num", "#", 4, "right", 30),
        Column("name", "File", 12, grow=3),
        Column("path", "Directory", 12, priority=40, grow=2),
        Column("size", "Size", 10, "right"),
        Column("type", "Type", 12, priority=20),
        Column("modified", "Modified", 13, "right", 10),
    ),
    marker_width=2,
)

CACHES = TableSchema(
    (
        Column("select", "", 3),
        Column("num", "#", 4, "right", 30),
        Column("name", "Cache", 12, grow=3),
        Column("category", "Category", 16, priority=40),
        Column("size", "Size", 10, "right"),
        Column("files", "Files", 8, "right", 20),
        Column("modified", "Modified", 13, "right", 10),
    ),
    marker_width=2,
)

XCODE = TableSchema(
    (
        Column("select", "", 3),
        Column("num", "#", 4, "right", 30),
        Column("name", "Item", 12, grow=3),
        Column("platform", "Platform", 10, priority=20),
        Column("size", "Size", 10, "right"),
        Column("modified", "Modified", 13, "right", 10),
        Column("badge", "", 8, priority=40),
    ),
    marker_width=2,
)

EXTENSIONS = TableSchema(
    (
        Column("name", "Extension", 10, grow=3),
        Column("count", "Count", 6, "right"),
        Column("size", "Size", 10, "right"),
        Column("percent", "%", 7, "right", 10),
    ),
    marker_width=0,
)

EXPLORER = TableSchema(
    (
        Column("select", "", 3),
        Column("name", "Name", 12, grow=3),
        Column("size", "Size", 10, "right"),
        Column("modified", "Modified", 13, "right", 20),
        Column("share", "Share", 8, priority=10),
    ),
    marker_width=0,
)
