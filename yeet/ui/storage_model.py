"""Storage segment values and file classification, independent of rendering."""

from dataclasses import dataclass

from ..models import DiskItem, LeftoverItem, PurgeArtifact, SelectableItem


@dataclass(frozen=True)
class Segment:
    label: str
    size: int
    color: str
    id: str | None = None


_FILE_GROUPS = {
    "Photos": ".jpg .jpeg .png .gif .webp .heic .heif .raw .cr2 .nef .tiff .tif .svg .avif .psd",
    "Videos": ".mp4 .mov .mkv .avi .webm .m4v .mpg .mpeg .wmv",
    "Music": ".mp3 .m4a .wav .flac .aac .ogg .aiff .alac",
    "Archives": ".zip .tar .gz .bz2 .xz .7z .rar .zst .tgz",
    "Installers": ".dmg .pkg .iso .img .msi",
    "Apps": ".app .exe .apk .ipa .appimage",
    "Developer": ".py .pyc .js .ts .tsx .jsx .rs .go .java .class .jar .o .a .so .dylib .wasm .sqlite .db",
    "Documents": ".pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .csv .epub .pages .numbers .key",
}
_EXTENSION_GROUP = {
    extension: group
    for group, extensions in _FILE_GROUPS.items()
    for extension in extensions.split()
}


def file_storage_group(item: SelectableItem | LeftoverItem | DiskItem) -> str:
    """Use supplied app/project ownership, then file type; never guess an app."""
    if isinstance(item, LeftoverItem) and item.app_hint:
        return item.app_hint
    for part in item.path.parts:
        if part.lower().endswith(".app"):
            return part[:-4]
    if isinstance(item, PurgeArtifact):
        return item.project_name
    return _EXTENSION_GROUP.get(item.path.suffix.lower(), "Other files")
