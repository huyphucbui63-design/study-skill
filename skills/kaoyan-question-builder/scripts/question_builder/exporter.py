"""Convert a reviewed question project into the print-kit's compatible manifest."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from qa_pdf import inspect as inspect_pdf

from .pdf_pipeline import crop_region


def _load_print_builder(repo_root: Path) -> Any:
    path = repo_root / "skills" / "kaoyan-print-kit" / "scripts" / "build_material.py"
    spec = importlib.util.spec_from_file_location("kaoyan_print_builder", path)
    if not spec or not spec.loader:
        raise RuntimeError("Could not load the shared print-kit generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_for_export(project: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    selected = [item for item in project.get("candidates", []) if item.get("selected")]
    if not selected:
        errors.append("至少选择一道题。")
    for item in selected:
        transcription = item.get("transcription") or {}
        label = item.get("question_number") or item["id"]
        if not transcription.get("stem", "").strip():
            errors.append(f"题目 {label} 尚未完成题干校对。")
        if transcription.get("uncertainties") and not transcription.get("uncertainties_confirmed"):
            errors.append(f"题目 {label} 仍有未确认的低置信度内容。")
        if (item.get("answer_suspect") or transcription.get("suspected_answer_leak")) and not transcription.get("answer_leak_reviewed"):
            errors.append(f"题目 {label} 含疑似答案区域，必须确认没有答案泄漏。")
        detected = int(item.get("subquestions_detected") or 0)
        actual = len(transcription.get("subquestions") or [])
        if detected and actual < detected and not transcription.get("subquestions_confirmed"):
            errors.append(f"题目 {label} 的小问数量可能遗漏。")
    return errors


def image_has_content(path: Path) -> bool:
    with Image.open(path) as source:
        image = source.convert("RGB")
        difference = ImageChops.difference(image, Image.new("RGB", image.size, "white")).convert("L")
        histogram = difference.histogram()
        nonwhite_pixels = sum(histogram[8:])
        return nonwhite_pixels >= max(20, int(image.width * image.height * 0.0002))


def build_manifest(project: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    settings = project.get("layout", {})
    numbering = settings.get("numbering", "preserve")
    selected = sorted((item for item in project["candidates"] if item.get("selected")), key=lambda item: item.get("order", 0))
    selected_by_id = {item["id"]: item for item in selected}
    continuation_parent: dict[str, str] = {}
    for item in selected:
        for relation in item.get("relations", []):
            parent_id = relation.get("candidate_id")
            if relation.get("type") == "continuation_of" and parent_id in selected_by_id:
                continuation_parent[item["id"]] = parent_id
                break
    def root_parent(item_id: str) -> str:
        seen = {item_id}
        while item_id in continuation_parent and continuation_parent[item_id] not in seen:
            item_id = continuation_parent[item_id]
            seen.add(item_id)
        return item_id
    grouped: list[list[dict[str, Any]]] = []
    groups_by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        parent_id = root_parent(item["id"])
        group = groups_by_parent.get(parent_id)
        if group is None:
            parent = selected_by_id.get(parent_id, item)
            group = [parent]
            groups_by_parent[parent_id] = group
            grouped.append(group)
        if item not in group:
            group.append(item)
    sections: list[dict[str, Any]] = []
    section_map: dict[str, dict[str, Any]] = {}
    for index, group in enumerate(grouped, start=1):
        item = group[0]
        transcription = item["transcription"]
        chapter = transcription.get("chapter") or item.get("chapter") or "原资料顺序"
        section = section_map.get(chapter)
        if section is None:
            section = {"title": chapter, "blocks": []}
            section_map[chapter] = section
            sections.append(section)
        source_parts = []
        for region_item in group:
            source = f"{region_item['source_file']} · PDF 第 {region_item.get('source_pdf_page', region_item['pdf_page'])} 页"
            if region_item.get("book_page"):
                source += f" · 原书第 {region_item['book_page']} 页"
            source_parts.append(source)
        number = str(index) if numbering == "continuous" else str(item.get("question_number") or index)
        block = {
            "type": "question", "id": item["id"], "number": number,
            "stem": "\n".join(part["transcription"]["stem"] for part in group if part["transcription"].get("stem")),
            "options": [option for part in group for option in part["transcription"].get("options", [])],
            "subquestions": [question for part in group for question in part["transcription"].get("subquestions", [])],
            "tables": [table for part in group for table in part["transcription"].get("tables", [])],
            "source": "；".join(source_parts),
            "answer_space_lines": int(settings.get("answer_space_lines", 5)), "graphics": [],
        }
        graphic_index = 0
        for region_item in group:
            page_path = project_dir / "pages" / f"page-{region_item['pdf_page']}.png"
            for bbox in region_item.get("preserve_graphics", []):
                graphic_index += 1
                graphic_path = project_dir / "assets" / f"{item['id']}-graphic-{graphic_index}.png"
                crop_region(page_path, bbox, graphic_path, padding=8)
                if not image_has_content(graphic_path):
                    graphic_path.unlink(missing_ok=True)
                    raise ValueError(f"题目 {item.get('question_number') or item['id']} 的必要图形框为空白，请重新框选。")
                block["graphics"].append({"path": str(graphic_path), "caption": "题目必要图形"})
        section["blocks"].append(block)
    return {
        "mode": "mistakes", "title": project.get("title") or "题目选编",
        "subject": project.get("subject") or "考研题目", "chapter": project.get("chapter") or "按原资料顺序",
        "print_profile": "bw", "include_toc": len(sections) > 1 or len({item["source_file"] for item in selected}) > 1,
        "sections": sections,
    }


def export_project(repo_root: Path, project: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    project_dir = project_dir.resolve()
    errors = validate_for_export(project)
    if errors:
        raise ValueError("\n".join(errors))
    manifest = build_manifest(project, project_dir)
    manifest_path = project_dir / "export-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    output_dir = project_dir / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    builder = _load_print_builder(repo_root)
    stem = builder.safe_name(manifest["title"])
    pdf_path = output_dir / f"{stem}.pdf"
    builder.build_pdf(manifest, "practice", pdf_path, manifest_path.parent)
    reader = builder.PdfReader(str(pdf_path))
    if not reader.pages or not any((page.extract_text() or "").strip() for page in reader.pages):
        raise RuntimeError("Generated PDF did not contain selectable text")
    required_sources = [
        block["source"]
        for section in manifest["sections"]
        for block in section.get("blocks", [])
    ]
    qa = inspect_pdf(
        pdf_path,
        project_dir / "qa-render",
        required_sources,
        [section["title"] for section in manifest["sections"]] if manifest.get("include_toc") else [],
        any(item.get("preserve_graphics") for item in project.get("candidates", []) if item.get("selected")),
    )
    if not qa["passed"]:
        raise RuntimeError("Generated PDF failed quality checks:\n" + "\n".join(qa["blockers"]))
    return {"manifest": str(manifest_path), "pdf": str(pdf_path), "pages": len(reader.pages), "qa": qa}
