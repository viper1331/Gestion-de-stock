from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import backend.core.services as services
import backend.core.storage as storage


def test_media_helpers_reject_path_traversal(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret")

    monkeypatch.setattr(services, "MEDIA_ROOT", media_root)
    monkeypatch.setattr(storage, "MEDIA_ROOT", media_root)

    services._delete_media_file("../outside.txt")

    assert outside_file.exists(), "Deletion must not escape MEDIA_ROOT"

    clone_dir = media_root / "clones"
    cloned = services._clone_media_file("../outside.txt", clone_dir)

    assert cloned is None
    assert not clone_dir.exists()


def test_clone_media_file_allows_valid_paths(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    source_dir = media_root / "uploads"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "image.jpg"
    source_file.write_bytes(b"binary-data")

    monkeypatch.setattr(services, "MEDIA_ROOT", media_root)
    monkeypatch.setattr(storage, "MEDIA_ROOT", media_root)

    relative_path = storage.relative_to_media(source_file)
    clone_dir = media_root / "clones"

    cloned_path = services._clone_media_file(relative_path, clone_dir)

    assert cloned_path is not None
    assert Path(media_root / cloned_path).exists()
