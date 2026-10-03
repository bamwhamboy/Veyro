from types import SimpleNamespace

import pytest

from app.ocr import OCRProviderError, TesseractOCRProvider


TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t92.0\tNIKE
5\t1\t1\t1\t1\t2\t22\t0\t30\t10\t86.0\tCT1234
5\t1\t1\t1\t1\t3\t52\t0\t0\t0\t-1\t
"""


def test_tesseract_adapter_parses_text_and_normalizes_confidence(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "label.jpg"
    image_path.write_bytes(b"test image bytes")
    monkeypatch.setattr("app.ocr.shutil.which", lambda executable: "/usr/bin/tesseract")
    monkeypatch.setattr(
        "app.ocr.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=TSV),
    )

    extraction = TesseractOCRProvider().extract(image_path)

    assert extraction.text == "NIKE CT1234"
    assert extraction.confidence == pytest.approx(0.89)


def test_tesseract_adapter_reports_missing_system_executable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.ocr.shutil.which", lambda executable: None)
    with pytest.raises(FileNotFoundError, match="Tesseract OCR is unavailable"):
        TesseractOCRProvider().extract(tmp_path / "label.jpg")


def test_tesseract_adapter_surfaces_processing_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.ocr.shutil.which", lambda executable: "/usr/bin/tesseract")

    def fail(*args, **kwargs):
        import subprocess

        raise subprocess.TimeoutExpired("tesseract", 30)

    monkeypatch.setattr("app.ocr.subprocess.run", fail)
    with pytest.raises(OCRProviderError, match="could not process"):
        TesseractOCRProvider().extract(tmp_path / "label.jpg")
