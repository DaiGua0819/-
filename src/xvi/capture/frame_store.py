from pathlib import Path
from uuid import UUID

from xvi.capture.hashes import image_dimensions, phash_bytes, sha256_bytes
from xvi.domain.enums import CaptureMethod
from xvi.domain.models import AssetMetadata


class FrameStore:
    """受控临时资产存储，不保存来源 CDN 地址。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        asset_id: UUID,
        note_id: UUID,
        source_index: int,
        data: bytes,
        capture_method: CaptureMethod,
    ) -> AssetMetadata:
        width, height, image_format = image_dimensions(data)
        sha256 = sha256_bytes(data)
        phash = phash_bytes(data)
        extension = "jpg" if image_format.upper() in {"JPEG", "JPG"} else image_format.lower()
        directory = self.root / str(note_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{source_index:03d}-{asset_id}.{extension}"
        path.write_bytes(data)
        return AssetMetadata(
            asset_id=asset_id,
            note_id=note_id,
            source_index=source_index,
            capture_method=capture_method,
            path=path,
            width=width,
            height=height,
            mime_type=f"image/{'jpeg' if extension == 'jpg' else extension}",
            sha256=sha256,
            phash=phash,
        )
