"""Centralise the storage paths used by the backend."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_ROOT = BASE_DIR / "media"
VEHICLE_CATEGORY_MEDIA_DIR = MEDIA_ROOT / "vehicle_categories"
VEHICLE_ITEM_MEDIA_DIR = MEDIA_ROOT / "vehicle_items"
VEHICLE_PHOTO_MEDIA_DIR = MEDIA_ROOT / "vehicle_photos"

for directory in (
    MEDIA_ROOT,
    VEHICLE_CATEGORY_MEDIA_DIR,
    VEHICLE_ITEM_MEDIA_DIR,
    VEHICLE_PHOTO_MEDIA_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


def relative_to_media(path: Path) -> str:
    """Return the relative POSIX path for a media file."""

    return path.relative_to(MEDIA_ROOT).as_posix()
