#!/usr/bin/env python3
"""Create a conservative draft memorization project from PDF, DOCX, images, or text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def source_type(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "pdf"
    if path.suffix.lower() == ".docx":
        return "docx"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    return "user_text"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_items(path: Path) -> list[tuple[str, dict[str, Any]]]:
    kind = source_type(path)
    if kind == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is required for PDF extraction") from exc
        reader = PdfReader(str(path))
        items = []
        for page_number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                items.append((text, {"pdf_page": page_number, "confidence": 0.75}))
            else:
                items.append((f"[待人工识别：PDF 第 {page_number} 页]", {"pdf_page": page_number, "confidence": 0.0}))
        return items
    if kind == "docx":
        try:
            from docx import Document
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as exc:
            raise RuntimeError("python-docx is required for DOCX extraction") from exc
        document = Document(str(path))
        items = []
        paragraph_number = 0
        table_number = 0
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraph_number += 1
                text = Paragraph(child, document).text.strip()
                if text:
                    items.append((text, {"docx_paragraph": paragraph_number, "confidence": 0.95}))
            elif isinstance(child, CT_Tbl):
                table_number += 1
                table = Table(child, document)
                rows = ["\t".join(cell.text.strip() for cell in row.cells) for row in table.rows]
                text = "\n".join(row for row in rows if row.strip())
                if text:
                    items.append((text, {"text_range": f"表格 {table_number}", "confidence": 0.9}))
        return items or [("[待人工补录：DOCX 没有可提取段落]", {"confidence": 0.0})]
    if kind == "image":
        return [(f"[待人工识别：{path.name}]", {"image_name": path.name, "confidence": 0.0})]
    text = path.read_text(encoding="utf-8")
    return [(text.strip() or "[待人工补录：空文本]", {"text_range": "全文", "confidence": 1.0})]


def draft_grading(statement: str) -> dict[str, Any]:
    evidence = {"kind": "ai_inference", "statement": statement, "confidence": 0.0}
    return {
        "importance": "C",
        "importance_status": "ai_suggestion",
        "importance_evidence": [dict(evidence)],
        "personal_weak": False,
        "weakness_status": "ai_suggestion",
        "weakness_evidence": [dict(evidence)],
    }


def draft_project(title: str, subject: str, paths: list[Path], user_texts: list[str] | None = None) -> dict[str, Any]:
    sources = []
    points = []
    for source_index, path in enumerate(paths, 1):
        source_id = f"source-{source_index}"
        source_kind = source_type(path)
        sources.append({"id": source_id, "source_order": source_index, "type": source_kind, "label": path.name, "path": str(path.resolve()), "sha256": sha256(path)})
        for item_index, (text, locator) in enumerate(extract_items(path), 1):
            point_id = f"p-{source_index}-{item_index}"
            points.append({
                "id": point_id,
                "source_order": len(points) + 1,
                "title": f"待确认知识点 {source_index}.{item_index}",
                "kind": "mixed",
                "grading": draft_grading("抽取器默认占位，需用户分别确认 A/B/C 与 R。"),
                "segments": [{
                    "origin": "source_text", "content": text, "verbatim": source_kind == "user_text",
                    "needs_review": source_kind != "user_text" or locator.get("confidence", 0.0) < 0.9,
                    "uncertainty": "自动草稿，需逐条核对。", "references": [{"source_id": source_id, **locator}],
                }],
            })
    for text_index, text in enumerate(user_texts or [], 1):
        source_number = len(sources) + 1
        source_id = f"source-{source_number}"
        label = f"用户文本 {text_index}"
        sources.append({"id": source_id, "source_order": source_number, "type": "user_text", "label": label, "path": ""})
        points.append({
            "id": f"p-{source_number}-1", "source_order": len(points) + 1,
            "title": f"待确认知识点 {source_number}.1", "kind": "mixed",
            "grading": draft_grading("抽取器默认占位，需用户分别确认 A/B/C 与 R。"),
            "segments": [{
                "origin": "source_text", "content": text, "verbatim": True, "needs_review": False,
                "references": [{"source_id": source_id, "text_range": "本次输入", "confidence": 1.0}],
            }],
        })
    return {
        "schema_version": "1.0", "title": title, "subject": subject,
        "scope": "待用户确认的来源顺序", "density": "standard", "sources": sources,
        "chapters": [{"id": "chapter-1", "source_order": 1, "title": "待确认章节", "points": points or [{
            "id": "p-1", "source_order": 1, "title": "待人工补录知识点", "kind": "mixed",
            "grading": draft_grading("无可提取内容，需用户分别确认 A/B/C 与 R。"),
            "segments": [{"origin": "user_note", "content": "请补录内容", "verbatim": True, "needs_review": True, "references": []}],
        }]}], "transformations": [],
        "review": {"status": "draft", "confirmed_at": None, "confirmed_by": "not_confirmed", "notes": "逐点核对来源、定义、公式、顺序和分级后再确认。"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", type=Path)
    parser.add_argument("--text", action="append", default=[], help="Verbatim user text; may be repeated")
    parser.add_argument("--title", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.sources and not args.text:
        parser.error("provide at least one source path or --text value")
    try:
        project = draft_project(args.title, args.subject, [path.resolve() for path in args.sources], args.text)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(args.output.resolve()), "review_status": "draft"}, ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
