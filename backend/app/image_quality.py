"""Image validation and basic capture-quality checks."""
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .domain import ImageQualityReport

_FORMATS = {
    "JPEG": "image/jpeg",
    # MPO is a multi-picture JPEG container. Pillow can inspect its first frame
    # and the submitted bytes remain JPEG encoded, so store/process it as JPEG.
    "MPO": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
_MAX_PIXELS = 30_000_000


class InvalidImageError(ValueError):
    pass


def inspect_uploaded_image(image_bytes: bytes) -> tuple[str, ImageQualityReport]:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            if image_format not in _FORMATS:
                detected = image_format or "unknown"
                raise InvalidImageError(
                    f"Unsupported image encoding '{detected}'. Use JPEG (.jpg or .jpeg), PNG, or WebP photos."
                )
            if image.width * image.height > _MAX_PIXELS:
                raise InvalidImageError("Image dimensions exceed the 30 megapixel limit")
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            width, height = image.size
            image.thumbnail((1200, 1200))
            grayscale = ImageOps.grayscale(image)
            brightness = ImageStat.Stat(grayscale).mean[0]
            sharpness = ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).var[0]
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidImageError("The uploaded file is not a readable image") from error

    issues: list[str] = []
    if width < 640 or height < 480:
        issues.append("low_resolution")
    if brightness < 18 or brightness > 238:
        issues.append("poor_lighting")
    if sharpness < 18:
        issues.append("possibly_blurry")

    return _FORMATS[image_format], ImageQualityReport(
        status="retake_recommended" if issues else "good",
        issues=issues,
        width=width,
        height=height,
        sharpness_score=round(sharpness, 2),
        brightness=round(brightness, 2),
    )
