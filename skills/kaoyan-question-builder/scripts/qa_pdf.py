#!/usr/bin/env python3
"""Render and verify a generated question PDF."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from pypdf import PdfReader

from question_builder.pdf_pipeline import locate_poppler


STANDARD_FONTS = {
    "/Courier", "/Courier-Bold", "/Courier-Oblique", "/Courier-BoldOblique",
    "/Helvetica", "/Helvetica-Bold", "/Helvetica-Oblique", "/Helvetica-BoldOblique",
    "/Times-Roman", "/Times-Bold", "/Times-Italic", "/Times-BoldItalic",
    "/Symbol", "/ZapfDingbats",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--render-dir", required=True, type=Path)
    parser.add_argument("--require-source", action="append", default=[])
    parser.add_argument("--toc-section", action="append", default=[])
    parser.add_argument("--require-images", action="store_true")
    return parser.parse_args()


def render(pdf: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("page-*.png"):
        stale.unlink()
    executable = locate_poppler("pdftoppm")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(executable).parent) + os.pathsep + environment.get("PATH", "")
    process = subprocess.run(
        [executable, "-png", "-r", "120", str(pdf), str(output_dir / "page")],
        capture_output=True, text=True, timeout=300, check=False, env=environment,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "PDF rendering failed")
    return sorted(output_dir.glob("page-*.png"), key=lambda item: int(item.stem.rsplit("-", 1)[1]))


def font_status(reader: PdfReader) -> tuple[list[str], list[str]]:
    embedded: set[str] = set()
    missing: set[str] = set()
    for page in reader.pages:
        fonts = page.get("/Resources", {}).get("/Font", {})
        for reference in fonts.values():
            font = reference.get_object()
            base_name = str(font.get("/BaseFont", "unknown"))
            descendants = [item.get_object() for item in font.get("/DescendantFonts", [])] or [font]
            has_file = False
            for descendant in descendants:
                descriptor = descendant.get("/FontDescriptor")
                if descriptor:
                    value = descriptor.get_object()
                    has_file = has_file or bool(value.get("/FontFile") or value.get("/FontFile2") or value.get("/FontFile3"))
            if has_file:
                embedded.add(base_name)
            elif base_name not in STANDARD_FONTS:
                missing.add(base_name)
    return sorted(embedded), sorted(missing)


def image_count(reader: PdfReader) -> int:
    count = 0
    for page in reader.pages:
        objects = page.get("/Resources", {}).get("/XObject", {})
        count += sum(1 for value in objects.values() if value.get_object().get("/Subtype") == "/Image")
    return count


def toc_findings(text_by_page: list[str], sections: list[str]) -> list[str]:
    if not sections:
        return []
    findings: list[str] = []
    toc_text = next((text for text in text_by_page if "目录" in text), "")
    if not toc_text:
        return ["缺少目录文本"]
    compact_toc = re.sub(r"\s+", " ", toc_text)
    for section in sections:
        actual = next((index for index, text in enumerate(text_by_page, start=1) if index > 1 and section in text), None)
        if actual is None:
            findings.append(f"未找到章节正文：{section}")
            continue
        after = re.escape(section) + r".{0,40}\b" + str(actual) + r"\b"
        before = r"\b" + str(actual) + r"\b.{0,40}" + re.escape(section)
        if not re.search(after, compact_toc) and not re.search(before, compact_toc):
            findings.append(f"目录页码与正文不匹配或无法验证：{section} -> {actual}")
    return findings


def inspect(pdf: Path, render_dir: Path, required_sources: list[str], toc_sections: list[str], require_images: bool) -> dict[str, Any]:
    reader = PdfReader(str(pdf))
    text_by_page = [(page.extract_text() or "").strip() for page in reader.pages]
    rendered = render(pdf, render_dir)
    nonblank = []
    for path in rendered:
        with Image.open(path) as source:
            image = source.convert("RGB")
            difference = ImageChops.difference(image, Image.new("RGB", image.size, "white"))
            nonblank.append(bool(difference.getbbox()))
    embedded, missing = font_status(reader)
    images = image_count(reader)
    combined_text = re.sub(r"\s+", " ", "\n".join(text_by_page))
    blockers = []
    if not reader.pages or len(rendered) != len(reader.pages):
        blockers.append("渲染页数与 PDF 页数不一致")
    blockers.extend(f"第 {index} 页渲染为空" for index, value in enumerate(nonblank, start=1) if not value)
    blockers.extend(f"第 {index} 页没有可选择文字" for index, value in enumerate(text_by_page, start=1) if not value)
    if not embedded:
        blockers.append("未检测到嵌入字体")
    blockers.extend(f"字体未嵌入：{name}" for name in missing)
    blockers.extend(f"缺少来源标注：{source}" for source in required_sources if source not in combined_text)
    if require_images and images < 1:
        blockers.append("未检测到必要图形")
    blockers.extend(toc_findings(text_by_page, toc_sections))
    return {
        "pdf": str(pdf.resolve()), "pages": len(reader.pages), "rendered_pages": len(rendered),
        "page_nonblank": nonblank, "selectable_text_pages": [bool(value) for value in text_by_page],
        "embedded_fonts": embedded, "unembedded_fonts": missing, "image_xobjects": images,
        "blockers": blockers, "passed": not blockers,
    }


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = inspect(args.pdf.resolve(), args.render_dir.resolve(), args.require_source, args.toc_section, args.require_images)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
