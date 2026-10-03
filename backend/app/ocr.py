"""Tesseract adapter implementing the replaceable OCR provider contract."""
from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import shutil
import subprocess

from .domain import OCRExtraction


class OCRProviderError(RuntimeError):
    pass


class TesseractOCRProvider:
    provider_name = "tesseract"

    def __init__(self, executable: str = "tesseract", timeout_seconds: int = 30) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def extract(self, image_path: Path) -> OCRExtraction:
        executable = shutil.which(self.executable)
        if executable is None:
            raise FileNotFoundError(
                "Tesseract OCR is unavailable; install Tesseract or configure another OCR provider"
            )
        try:
            result = subprocess.run(
                [executable, str(image_path), "stdout", "--psm", "6", "tsv"],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise OCRProviderError("Tesseract could not process the uploaded photo") from error

        words: list[str] = []
        confidences: list[float] = []
        for row in csv.DictReader(StringIO(result.stdout), delimiter="\t"):
            word = (row.get("text") or "").strip()
            if not word:
                continue
            words.append(word)
            try:
                confidence = float(row.get("conf", "-1"))
            except ValueError:
                continue
            if confidence >= 0:
                confidences.append(confidence / 100.0)

        return OCRExtraction(
            text=" ".join(words),
            confidence=(sum(confidences) / len(confidences)) if confidences else None,
        )
