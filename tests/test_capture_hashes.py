from io import BytesIO

from PIL import Image

from xvi.capture.hashes import image_dimensions, phash_bytes, sha256_bytes


def test_png_metadata_is_stable() -> None:
    output = BytesIO()
    Image.new("RGB", (8, 6), "red").save(output, format="PNG")
    data = output.getvalue()
    assert image_dimensions(data) == (8, 6, "PNG")
    assert sha256_bytes(data) == sha256_bytes(data)
    assert phash_bytes(data)
