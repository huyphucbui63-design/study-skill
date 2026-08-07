"""Low-cost PDF boundary detection, page rendering, and source-region crops."""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
import os
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image
from pypdf import PdfReader


QUESTION_START = re.compile(r"^\s*(?:第\s*)?(\d{1,4})(?:\s*[题、.]|\s*\.(?!\d)|\s+)")
SUBQUESTION_START = re.compile(r"^\s*[（(]\s*(\d{1,2})\s*[）)]")
ANSWER_SIGNAL = re.compile(r"(?:答案|解析|参考答案|解[:：]|【答案】)")
SHARED_STEM_SIGNAL = re.compile(r"(?:共用题干|根据下列材料|回答下列|完成第\s*\d+\s*[—~-]\s*\d+\s*题)")
BOOK_PAGE = re.compile(r"^\s*(?:[-—]\s*)?(\d{1,4})(?:\s*[-—])?\s*$")


def locate_poppler(binary: str) -> str:
    runtime = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "native" / "poppler" / "Library" / "bin" / f"{binary}.exe"
    if runtime.is_file():
        return str(runtime)
    found = shutil.which(binary)
    if found:
        return found
    raise RuntimeError(f"{binary} is required. Install Poppler or use the Codex bundled runtime.")


def render_pdf(source_pdf: Path, pages_dir: Path, dpi: int = 120) -> list[dict[str, Any]]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    prefix = pages_dir / "page"
    poppler = locate_poppler("pdftoppm")
    command = [poppler, "-png", "-r", str(dpi), str(source_pdf), str(prefix)]
    environment = os.environ.copy()
    environment["PATH"] = str(Path(poppler).parent) + os.pathsep + environment.get("PATH", "")
    process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False, env=environment)
    if process.returncode:
        raise RuntimeError(f"Could not render PDF pages: {process.stderr.strip()}")
    images = sorted(pages_dir.glob("page-*.png"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
    result = []
    for index, path in enumerate(images, start=1):
        with Image.open(path) as image:
            result.append({"pdf_page": index, "width": image.width, "height": image.height, "image": f"pages/{path.name}"})
    return result


def _book_page(words: list[dict[str, Any]], page_height: float) -> str | None:
    footer = [word for word in words if float(word.get("top", 0)) > page_height * 0.88]
    for word in sorted(footer, key=lambda item: item.get("x0", 0)):
        match = BOOK_PAGE.match(str(word.get("text", "")))
        if match:
            return match.group(1)
    return None


def detect_boundaries(source_pdf: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect starts from PDF words; never OCR or invent missing text in this phase."""
    reader = PdfReader(str(source_pdf))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported until the user supplies an unlocked copy.")
    candidates: list[dict[str, Any]] = []
    pages_meta: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    with pdfplumber.open(source_pdf) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False, x_tolerance=2, y_tolerance=3)
            book_page = _book_page(words, page.height)
            lines: list[dict[str, Any]] = []
            for word in words:
                top = round(float(word["top"]), 1)
                line = next((item for item in lines if abs(item["top"] - top) <= 3.5), None)
                if line is None:
                    line = {"top": top, "bottom": float(word["bottom"]), "x0": float(word["x0"]), "x1": float(word["x1"]), "words": []}
                    lines.append(line)
                line["words"].append(word)
                line["bottom"] = max(line["bottom"], float(word["bottom"]))
                line["x0"] = min(line["x0"], float(word["x0"]))
                line["x1"] = max(line["x1"], float(word["x1"]))
            for line in lines:
                line["text"] = " ".join(str(word["text"]) for word in sorted(line["words"], key=lambda item: item["x0"]))
            starts = [(idx, QUESTION_START.match(line["text"])) for idx, line in enumerate(lines)]
            starts = [(idx, match) for idx, match in starts if match]
            pages_meta.append({"pdf_page": page_index, "book_page": book_page, "has_text_layer": bool(words)})
            if not starts:
                candidate = {
                    "id": f"q-{uuid.uuid4().hex[:10]}", "selected": False, "order": len(candidates) + 1,
                    "question_number": None, "source_file": source_pdf.name, "pdf_page": page_index,
                    "book_page": book_page, "bbox": [0.04, 0.04, 0.96, 0.96], "confidence": 0.15,
                    "relations": [], "shared_stem": False, "subquestions_detected": 0,
                    "answer_suspect": False, "manual_reason": "页面无可靠题号文本；请手动调整或拆分候选框。",
                    "preserve_graphics": [], "transcription": None,
                }
                candidates.append(candidate)
                previous = candidate
                continue
            for position, (line_index, match) in enumerate(starts):
                line = lines[line_index]
                next_top = lines[starts[position + 1][0]]["top"] if position + 1 < len(starts) else page.height * 0.96
                region_lines = [item for item in lines if line["top"] <= item["top"] < next_top]
                text_preview = "\n".join(item["text"] for item in region_lines)
                bbox = [
                    max(0.0, min(item["x0"] for item in region_lines) / page.width - 0.012),
                    max(0.0, line["top"] / page.height - 0.008),
                    min(1.0, max(item["x1"] for item in region_lines) / page.width + 0.012),
                    min(1.0, next_top / page.height - 0.004),
                ]
                number = match.group(1)
                subquestions = sum(bool(SUBQUESTION_START.match(item["text"])) for item in region_lines)
                candidate = {
                    "id": f"q-{uuid.uuid4().hex[:10]}", "selected": True, "order": len(candidates) + 1,
                    "question_number": number, "source_file": source_pdf.name, "pdf_page": page_index,
                    "book_page": book_page, "bbox": [round(value, 5) for value in bbox], "confidence": 0.78,
                    "relations": [], "shared_stem": bool(SHARED_STEM_SIGNAL.search(text_preview)),
                    "subquestions_detected": subquestions, "answer_suspect": bool(ANSWER_SIGNAL.search(text_preview)),
                    "manual_reason": None, "preview_text": text_preview[:240], "preserve_graphics": [], "transcription": None,
                }
                if previous and previous["question_number"] == number and previous["pdf_page"] == page_index - 1:
                    candidate["relations"].append({"type": "continuation_of", "candidate_id": previous["id"]})
                    candidate["confidence"] = 0.62
                candidates.append(candidate)
                previous = candidate
    return candidates, pages_meta


def crop_region(page_image: Path, bbox: list[float], output: Path, padding: int = 4) -> Path:
    if len(bbox) != 4 or not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
        raise ValueError("bbox must be normalized [x0,y0,x1,y1]")
    with Image.open(page_image) as image:
        x0, y0, x1, y1 = bbox
        box = (
            max(0, int(x0 * image.width) - padding), max(0, int(y0 * image.height) - padding),
            min(image.width, int(x1 * image.width) + padding), min(image.height, int(y1 * image.height) + padding),
        )
        cropped = image.crop(box)
        output.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output, "PNG")
    return output


def merge_candidates(items: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    selected = [item for item in items if item["id"] in ids]
    if len(selected) < 2:
        raise ValueError("Select at least two candidates to merge")
    selected.sort(key=lambda item: (item["pdf_page"], item["bbox"][1], item["order"]))
    if any(item.get("transcription") is not None for item in selected):
        raise ValueError("Merge boundaries before recognition or clear reviewed transcriptions explicitly")
    if len({(item["source_file"], item["pdf_page"]) for item in selected}) != 1:
        raise ValueError("Merge only candidates split incorrectly on the same PDF page; use cross-page linking for continuations")
    first = selected[0]
    first["bbox"] = [
        min(item["bbox"][0] for item in selected), min(item["bbox"][1] for item in selected),
        max(item["bbox"][2] for item in selected), max(item["bbox"][3] for item in selected),
    ]
    first["relations"] = [{"type": "merged_from", "candidate_ids": [item["id"] for item in selected]}]
    first["confidence"] = min(item["confidence"] for item in selected)
    first["answer_suspect"] = any(item.get("answer_suspect") for item in selected)
    first["subquestions_detected"] = sum(int(item.get("subquestions_detected") or 0) for item in selected)
    first["preserve_graphics"] = [box for item in selected for box in item.get("preserve_graphics", [])]
    result = [item for item in items if item["id"] not in ids or item is first]
    for order, item in enumerate(sorted(result, key=lambda value: value["order"]), start=1):
        item["order"] = order
    return result


def split_candidate(items: list[dict[str, Any]], candidate_id: str, split_y: float) -> list[dict[str, Any]]:
    if not 0.02 < split_y < 0.98:
        raise ValueError("split_y must be normalized and inside the page")
    target = next((item for item in items if item["id"] == candidate_id), None)
    if not target:
        raise ValueError("Candidate not found")
    x0, y0, x1, y1 = target["bbox"]
    if target.get("transcription") is not None:
        raise ValueError("Split boundaries before recognition or clear the reviewed transcription explicitly")
    absolute_y = y0 + (y1 - y0) * split_y
    if absolute_y - y0 < 0.02 or y1 - absolute_y < 0.02:
        raise ValueError("Split would create an unusably small candidate")
    new_item = {**target, "id": f"q-{uuid.uuid4().hex[:10]}", "bbox": [x0, absolute_y, x1, y1], "question_number": None, "confidence": min(target["confidence"], 0.5), "manual_reason": "由人工拆分，请核对题号与边界。", "transcription": None}
    target["bbox"] = [x0, y0, x1, absolute_y]
    result = []
    for item in items:
        result.append(item)
        if item is target:
            result.append(new_item)
    for order, item in enumerate(result, start=1):
        item["order"] = order
    return result
