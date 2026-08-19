import hashlib
from io import BytesIO

import imagehash
from PIL import Image, UnidentifiedImageError


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_dimensions(data: bytes) -> tuple[int, int, str]:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.width, image.height, image.format or "UNKNOWN"
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("图片无法解码") from exc


def phash_bytes(data: bytes) -> str:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            return str(imagehash.phash(image.convert("RGB")))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("图片无法计算 pHash") from exc
