#!/usr/bin/env python3
"""Run structural QA checks on a generated memorization PDF."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

from pypdf import PdfReader
from pypdf.generic import ContentStream


def parse_toc_entries(values: list[str]) -> list[tuple[str, int]]:
    entries = []
    for value in values:
        title, separator, page = value.rpartition("=")
        if not separator or not title.strip() or not page.isdigit() or int(page) < 1:
            raise ValueError(f"Invalid TOC entry {value!r}; use TITLE=PAGE")
        entries.append((title.strip(), int(page)))
    return entries


def compose_matrix(
    first: tuple[float, float, float, float, float, float],
    second: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = first
    g, h, i, j, k, l = second
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def image_placements(reader: PdfReader, page_number: int) -> list[dict[str, object]]:
    page = reader.pages[page_number - 1]
    resources = page.get("/Resources", {})
    if hasattr(resources, "get_object"):
        resources = resources.get_object()
    xobjects = resources.get("/XObject", {}) if resources else {}
    if hasattr(xobjects, "get_object"):
        xobjects = xobjects.get_object()
    contents = page.get_contents()
    if contents is None:
        return []
    stream = ContentStream(contents, reader)
    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    current = identity
    stack: list[tuple[float, float, float, float, float, float]] = []
    placements = []
    for operands, operator in stream.operations:
        if operator == b"q":
            stack.append(current)
        elif operator == b"Q":
            current = stack.pop() if stack else identity
        elif operator == b"cm" and len(operands) == 6:
            matrix = tuple(float(value) for value in operands)
            current = compose_matrix(current, matrix)  # type: ignore[arg-type]
        elif operator == b"Do" and operands:
            name = operands[0]
            raw_object = xobjects.get(name) if xobjects else None
            if raw_object is None:
                continue
            image = raw_object.get_object()
            if image.get("/Subtype") != "/Image":
                continue
            display_width = math.hypot(current[0], current[1])
            display_height = math.hypot(current[2], current[3])
            if display_width <= 0 or display_height <= 0:
                continue
            pixel_width = int(image.get("/Width", 0))
            pixel_height = int(image.get("/Height", 0))
            dpi_x = pixel_width * 72.0 / display_width
            dpi_y = pixel_height * 72.0 / display_height
            placements.append({
                "page": page_number,
                "xobject": str(name),
                "pixels": [pixel_width, pixel_height],
                "display_points": [round(display_width, 2), round(display_height, 2)],
                "effective_dpi": round(min(dpi_x, dpi_y), 2),
            })
    return placements


def outline_destinations(reader: PdfReader) -> list[dict[str, object]]:
    destinations = []

    def visit(items: list[object]) -> None:
        for item in items:
            if isinstance(item, list):
                visit(item)
                continue
            title = getattr(item, "title", None)
            if not title:
                continue
            page_index = reader.get_destination_page_number(item)
            destinations.append({"title": str(title), "page": page_index + 1})

    visit(reader.outline)
    return destinations


def check_pdf(
    path: Path,
    required_text: list[str],
    toc_entries: list[tuple[str, int]] | None = None,
    min_images: int = 0,
    min_image_dpi: float = 150.0,
) -> dict[str, object]:
    reader = PdfReader(str(path))
    page_text = [(page.extract_text() or "") for page in reader.pages]
    fonts = set()
    unembedded_fonts = set()
    image_xobjects = 0
    placements = []
    for page_number, page in enumerate(reader.pages, 1):
        resources = page.get("/Resources", {})
        if hasattr(resources, "get_object"):
            resources = resources.get_object()
        font_dict = resources.get("/Font", {}) if resources else {}
        if hasattr(font_dict, "get_object"):
            font_dict = font_dict.get_object()
        for key, raw_font in font_dict.items():
            fonts.add(str(key))
            font = raw_font.get_object()
            base_font = str(font.get("/BaseFont", ""))
            descriptor = font.get("/FontDescriptor")
            if descriptor:
                descriptor = descriptor.get_object()
            embedded = bool(descriptor and any(descriptor.get(name) for name in ("/FontFile", "/FontFile2", "/FontFile3")))
            standard_14 = base_font.lstrip("/") in {"Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier", "Courier-Bold", "Symbol", "ZapfDingbats"}
            if not embedded and not standard_14:
                unembedded_fonts.add(base_font or str(key))
        xobjects = resources.get("/XObject", {}) if resources else {}
        if hasattr(xobjects, "get_object"):
            xobjects = xobjects.get_object()
        for raw_object in xobjects.values():
            if raw_object.get_object().get("/Subtype") == "/Image":
                image_xobjects += 1
        placements.extend(image_placements(reader, page_number))
    missing = [text for text in required_text if not any(text in content for content in page_text)]
    toc_text = "\n".join(text for text in page_text if "目录" in text)
    normalized_toc = re.sub(r"\s+", " ", toc_text)
    destinations = outline_destinations(reader)
    toc_mismatches = []
    for title, page_number in toc_entries or []:
        normalized_title = re.sub(r"\s+", " ", title)
        before = rf"(?:^|\s){page_number}\s+{re.escape(normalized_title)}(?:\s|$)"
        after = rf"(?:^|\s){re.escape(normalized_title)}\s+{page_number}(?:\s|$)"
        directory_ok = bool(re.search(before, normalized_toc) or re.search(after, normalized_toc))
        heading_ok = (
            page_number <= len(page_text)
            and normalized_title in re.sub(r"\s+", " ", page_text[page_number - 1])
        )
        bookmark_ok = any(
            item["title"] == title and item["page"] == page_number
            for item in destinations
        )
        if not directory_ok or not heading_ok or not bookmark_ok:
            toc_mismatches.append({
                "title": title,
                "expected_page": page_number,
                "directory_text_matches": directory_ok,
                "heading_on_expected_page": heading_ok,
                "bookmark_matches": bookmark_ok,
            })
    low_dpi_images = [
        item for item in placements
        if float(item["effective_dpi"]) + 0.05 < min_image_dpi
    ]
    unmeasured_images = max(0, image_xobjects - len(placements))
    return {
        "path": str(path), "pages": len(reader.pages), "nonempty_pages": sum(bool(text.strip()) for text in page_text),
        "selectable_text": any(text.strip() for text in page_text), "font_resources": sorted(fonts),
        "unembedded_nonstandard_fonts": sorted(unembedded_fonts), "missing_required_text": missing,
        "toc_mismatches": toc_mismatches, "outline_destinations": destinations,
        "image_xobjects": image_xobjects, "image_placements": placements,
        "minimum_images": min_images, "minimum_image_dpi": min_image_dpi,
        "low_dpi_images": low_dpi_images, "unmeasured_images": unmeasured_images,
        "ok": bool(reader.pages) and not missing and not unembedded_fonts and not toc_mismatches
        and image_xobjects >= min_images and not low_dpi_images and not unmeasured_images
        and all(text.strip() for text in page_text),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--required", action="append", default=[])
    parser.add_argument("--toc-entry", action="append", default=[], help="Expected PDF directory mapping as TITLE=PAGE")
    parser.add_argument("--min-images", type=int, default=0, help="Minimum number of embedded image XObjects")
    parser.add_argument("--min-image-dpi", type=float, default=150.0, help="Minimum effective DPI for every placed image")
    args = parser.parse_args()
    try:
        if args.min_images < 0:
            raise ValueError("--min-images cannot be negative")
        if args.min_image_dpi < 0:
            raise ValueError("--min-image-dpi cannot be negative")
        result = check_pdf(
            args.pdf.expanduser().resolve(),
            args.required,
            parse_toc_entries(args.toc_entry),
            args.min_images,
            args.min_image_dpi,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
