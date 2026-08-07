"""Validation and print-kit conversion for memorization projects."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any

ORIGIN_LABELS = {
    "source_text": "来源原文",
    "ai_summary": "AI 概括",
    "ai_memory_aid": "AI 记忆提示",
    "ai_example": "AI 例子",
    "user_note": "用户补充",
}
SOURCE_TYPES = {"pdf", "docx", "image", "user_text"}
EVIDENCE_KINDS = {"user_designation", "exam_requirement", "source_emphasis", "historical_question", "retained_study_record", "ai_inference"}
VISUAL_TYPES = {"comparison", "process", "timeline", "relationship", "image"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
TRANSFORMATION_TARGET_PATTERN = re.compile(r"^(sources|chapters|chapter:[A-Za-z0-9._-]+)$")


def _reject_extra(value: dict[str, Any], allowed: set[str], context: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(f"Unexpected field(s) in {context}: {', '.join(extra)}")


def _valid_id(value: Any, context: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid ID in {context}: {value!r}")
    return value


def _validate_order(items: list[dict[str, Any]], context: str, allow_reorder: bool) -> None:
    values = [item.get("source_order") for item in items]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values) or len(values) != len(set(values)):
        raise ValueError(f"source_order values must be positive and unique: {context}")
    if values != sorted(values) and not allow_reorder:
        raise ValueError(f"Source order changed without an authorized user transformation: {context}")


def _confidence(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError(f"Confidence must be between 0 and 1: {context}")
    return float(value)


def _datetime(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"A date-time is required: {context}")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid date-time: {context}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Date-time must include a timezone: {context}")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_source_paths(project: dict[str, Any], project_dir: Path) -> None:
    sources = project.get("sources")
    if not isinstance(sources, list):
        return
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            continue
        context = f"source {index}"
        raw_path = source["path"]
        if not raw_path.strip():
            if source.get("type") != "user_text":
                raise ValueError(f"Source file path is required: {context}")
            if source.get("sha256") is not None:
                raise ValueError(f"sha256 cannot be verified for inline user text: {context}")
            continue
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            source_path = project_dir / source_path
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise ValueError(f"Source file not found: {source_path}")
        expected_hash = source.get("sha256")
        if expected_hash is not None:
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
                raise ValueError(f"Invalid sha256: {context}")
            if _file_sha256(source_path) != expected_hash:
                raise ValueError(f"Source sha256 mismatch: {context} ({source_path})")
        source["path"] = str(source_path)


def _validate_reference(reference: dict[str, Any], sources: dict[str, dict[str, Any]], context: str) -> None:
    if not isinstance(reference, dict):
        raise ValueError(f"Source reference must be an object: {context}")
    _reject_extra(reference, {"source_id", "pdf_page", "book_page", "docx_paragraph", "heading", "image_name", "text_range", "confidence"}, context)
    source_label(reference, sources)
    for key in ("pdf_page", "docx_paragraph"):
        value = reference.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ValueError(f"{key} must be a one-based integer: {context}")
    if "confidence" in reference:
        _confidence(reference["confidence"], context)
    book_page = reference.get("book_page")
    if book_page is not None and (isinstance(book_page, bool) or not isinstance(book_page, (int, str))):
        raise ValueError(f"book_page must be an integer, string, or null: {context}")


def _validate_evidence_items(
    evidence: Any, sources: dict[str, dict[str, Any]], context: str
) -> list[dict[str, Any]]:
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"Evidence is required: {context}")
    for evidence_index, item in enumerate(evidence, 1):
        evidence_context = f"{context} / evidence {evidence_index}"
        if not isinstance(item, dict) or item.get("kind") not in EVIDENCE_KINDS or not str(item.get("statement", "")).strip():
            raise ValueError(f"Invalid grading evidence: {evidence_context}")
        _reject_extra(item, {"kind", "statement", "confidence", "reference"}, evidence_context)
        _confidence(item.get("confidence"), evidence_context)
        if item.get("reference") is not None:
            _validate_reference(item["reference"], sources, evidence_context)
    return evidence


def _validate_visual(
    visual: dict[str, Any], sources: dict[str, dict[str, Any]], context: str, require_confirmed: bool
) -> None:
    if not isinstance(visual, dict) or visual.get("type") not in VISUAL_TYPES or not str(visual.get("title", "")).strip():
        raise ValueError(f"Invalid visual structure: {context}")
    _reject_extra(visual, {"type", "title", "origin", "needs_review", "references", "headers", "rows", "items", "relations", "path", "caption"}, context)
    origin = visual.get("origin")
    if origin not in ORIGIN_LABELS or not isinstance(visual.get("needs_review"), bool) or not isinstance(visual.get("references"), list):
        raise ValueError(f"Visual origin, review state, and references are required: {context}")
    if require_confirmed and visual["needs_review"]:
        raise ValueError(f"Unresolved visual structure: {context}")
    if origin == "source_text" and not visual["references"]:
        raise ValueError(f"Source-derived visuals require a source reference: {context}")
    for reference in visual["references"]:
        _validate_reference(reference, sources, context)
    kind = visual["type"]
    if kind == "comparison":
        headers, rows = visual.get("headers"), visual.get("rows")
        if not isinstance(headers, list) or not headers or not isinstance(rows, list) or not rows or any(not isinstance(row, list) or len(row) != len(headers) for row in rows):
            raise ValueError(f"Comparison headers and rows must have equal widths: {context}")
    elif kind in {"process", "timeline"}:
        if not isinstance(visual.get("items"), list) or not visual["items"]:
            raise ValueError(f"{kind} requires items: {context}")
    elif kind == "relationship":
        relations = visual.get("relations")
        if not isinstance(relations, list) or not relations or any(not all(str(item.get(key, "")).strip() for key in ("from", "relation", "to")) for item in relations if isinstance(item, dict)) or any(not isinstance(item, dict) for item in relations):
            raise ValueError(f"Relationship entries require from, relation, and to: {context}")
        for relation in relations:
            _reject_extra(relation, {"from", "relation", "to"}, context)
    elif not str(visual.get("path", "")).strip():
        raise ValueError(f"Image visual requires a path: {context}")


def load_project(path: Path) -> dict[str, Any]:
    project_path = path.expanduser().resolve()
    try:
        value = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read project: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Project must be one JSON object.")
    _resolve_source_paths(value, project_path.parent)
    return value


def source_label(reference: dict[str, Any], sources: dict[str, dict[str, Any]]) -> str:
    source_id = reference.get("source_id")
    source = sources.get(str(source_id))
    if not source:
        raise ValueError(f"Unknown source_id: {source_id}")
    bits = [source["label"]]
    if reference.get("pdf_page"):
        bits.append(f"PDF 第 {reference['pdf_page']} 页")
    if reference.get("book_page") is not None:
        bits.append(f"原书第 {reference['book_page']} 页")
    if reference.get("docx_paragraph"):
        bits.append(f"段落 {reference['docx_paragraph']}")
    if reference.get("heading"):
        bits.append(str(reference["heading"]))
    if reference.get("image_name"):
        bits.append(str(reference["image_name"]))
    if reference.get("text_range"):
        bits.append(str(reference["text_range"]))
    return " · ".join(bits)


def validate_project(project: dict[str, Any], *, require_confirmed: bool = True) -> None:
    if not isinstance(project, dict):
        raise ValueError("Project must be one JSON object")
    _reject_extra(project, {"schema_version", "title", "subject", "scope", "density", "sources", "chapters", "transformations", "review"}, "project")
    required = ("schema_version", "title", "subject", "sources", "chapters", "review")
    missing = [key for key in required if key not in project]
    if missing:
        raise ValueError(f"Missing project fields: {', '.join(missing)}")
    if project["schema_version"] != "1.0":
        raise ValueError("Unsupported schema_version")
    if not str(project.get("title", "")).strip() or not str(project.get("subject", "")).strip():
        raise ValueError("title and subject are required")
    if project.get("density", "standard") not in {"compact", "standard", "spacious"}:
        raise ValueError("density must be compact, standard, or spacious")
    if not isinstance(project["sources"], list) or not isinstance(project["chapters"], list):
        raise ValueError("sources and chapters must be lists")
    if not project["chapters"]:
        raise ValueError("At least one chapter is required")
    transformations = project.get("transformations", [])
    if not isinstance(transformations, list):
        raise ValueError("transformations must be a list")
    for index, transformation in enumerate(transformations, 1):
        context = f"transformation {index}"
        if not isinstance(transformation, dict):
            raise ValueError(f"{context} must be an object")
        _reject_extra(transformation, {"type", "target", "authorized_by", "authorized_at", "details"}, context)
        target = transformation.get("target")
        if (
            transformation.get("type") not in {"reorder", "merge", "regroup", "rewrite_definition"}
            or not isinstance(target, str)
            or not TRANSFORMATION_TARGET_PATTERN.fullmatch(target)
            or transformation.get("authorized_by") != "user"
            or not str(transformation.get("details", "")).strip()
        ):
            raise ValueError(f"Invalid or unauthorized {context}")
        _datetime(transformation.get("authorized_at"), context)
    reorder_targets = {
        item["target"] for item in transformations if item["type"] in {"reorder", "regroup"}
    }
    for source_index, source in enumerate(project["sources"], 1):
        context = f"source {source_index}"
        if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES or not str(source.get("label", "")).strip() or not isinstance(source.get("path"), str):
            raise ValueError(f"{context} is incomplete")
        _reject_extra(source, {"id", "source_order", "type", "label", "path", "sha256"}, context)
        _valid_id(source.get("id"), context)
        sha256 = source.get("sha256")
        if sha256 is not None and (not isinstance(sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", sha256)):
            raise ValueError(f"Invalid sha256: {context}")
    _validate_order(project["sources"], "sources", "sources" in reorder_targets)
    source_ids = [item.get("id") for item in project["sources"]]
    if any(not item for item in source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("Source IDs must be present and unique")
    source_map = {item["id"]: item for item in project["sources"]}
    _validate_order(project["chapters"], "chapters", "chapters" in reorder_targets)
    chapter_ids: set[str] = set()
    point_ids: set[str] = set()
    for chapter_index, chapter in enumerate(project["chapters"], 1):
        if not isinstance(chapter, dict) or not chapter.get("id") or not str(chapter.get("title", "")).strip() or not chapter.get("points"):
            raise ValueError(f"Chapter {chapter_index} is incomplete")
        _reject_extra(chapter, {"id", "source_order", "title", "points"}, f"chapter {chapter_index}")
        _valid_id(chapter["id"], f"chapter {chapter_index}")
        if chapter["id"] in chapter_ids:
            raise ValueError(f"Chapter IDs must be unique: {chapter['id']}")
        chapter_ids.add(chapter["id"])
        if not isinstance(chapter["points"], list):
            raise ValueError(f"points must be a list: {chapter['title']}")
        _validate_order(
            chapter["points"],
            f"points in {chapter['title']}",
            f"chapter:{chapter['id']}" in reorder_targets,
        )
        for point_index, point in enumerate(chapter["points"], 1):
            context = f"{chapter['title']} / point {point_index}"
            point_id = point.get("id")
            if not point_id or point_id in point_ids or not str(point.get("title", "")).strip():
                raise ValueError(f"Knowledge point IDs must be present and unique: {context}")
            _reject_extra(point, {"id", "source_order", "title", "kind", "grading", "segments", "visuals", "recall_lines"}, context)
            _valid_id(point_id, context)
            if point.get("kind", "mixed") not in {"definition", "formula", "theorem", "timeline", "vocabulary", "mixed"}:
                raise ValueError(f"Invalid knowledge point kind: {context}")
            point_ids.add(point_id)
            grading = point.get("grading", {})
            if not isinstance(grading, dict):
                raise ValueError(f"grading must be an object: {context}")
            _reject_extra(
                grading,
                {
                    "importance",
                    "importance_status",
                    "importance_evidence",
                    "personal_weak",
                    "weakness_status",
                    "weakness_evidence",
                },
                f"grading in {context}",
            )
            if grading.get("importance") not in {"A", "B", "C"}:
                raise ValueError(f"Invalid A/B/C importance: {context}")
            if not isinstance(grading.get("personal_weak"), bool):
                raise ValueError(f"personal_weak must be boolean: {context}")
            importance_evidence = _validate_evidence_items(
                grading.get("importance_evidence"), source_map, f"importance in {context}"
            )
            weakness_evidence = _validate_evidence_items(
                grading.get("weakness_evidence"), source_map, f"weakness in {context}"
            )
            importance_status = grading.get("importance_status")
            weakness_status = grading.get("weakness_status")
            if importance_status not in {"confirmed", "ai_suggestion"}:
                raise ValueError(f"Invalid importance status: {context}")
            if weakness_status not in {"confirmed", "ai_suggestion"}:
                raise ValueError(f"Invalid weakness status: {context}")
            if require_confirmed and importance_status != "confirmed":
                raise ValueError(f"Unconfirmed A/B/C importance suggestion: {context}")
            if require_confirmed and weakness_status != "confirmed":
                raise ValueError(f"Unconfirmed R weakness suggestion: {context}")
            if weakness_status == "confirmed" and grading["personal_weak"] and any(
                item["kind"] not in {"user_designation", "retained_study_record"}
                for item in weakness_evidence
            ):
                raise ValueError(
                    f"A confirmed R marker accepts only user or retained-record evidence: {context}"
                )
            segments = point.get("segments")
            if not isinstance(segments, list) or not segments:
                raise ValueError(f"At least one content segment is required: {context}")
            for segment in segments:
                if not isinstance(segment, dict):
                    raise ValueError(f"Content segment must be an object: {context}")
                _reject_extra(segment, {"origin", "content", "verbatim", "needs_review", "uncertainty", "references"}, f"segment in {context}")
                origin = segment.get("origin")
                if origin not in ORIGIN_LABELS:
                    raise ValueError(f"Unknown content origin: {context}")
                if not str(segment.get("content", "")).strip():
                    raise ValueError(f"Empty content segment: {context}")
                if not isinstance(segment.get("verbatim"), bool) or not isinstance(segment.get("needs_review"), bool):
                    raise ValueError(f"verbatim and needs_review must be boolean: {context}")
                if segment["needs_review"] and require_confirmed:
                    raise ValueError(f"Unresolved content fragment: {context}")
                if require_confirmed and origin == "source_text" and not segment["verbatim"]:
                    raise ValueError(f"Confirmed source text must be verified as verbatim: {context}")
                if origin == "user_note" and not segment["verbatim"]:
                    raise ValueError(f"User notes must be preserved verbatim: {context}")
                if origin.startswith("ai_") and segment["verbatim"]:
                    raise ValueError(f"AI-authored content cannot be marked verbatim: {context}")
                references = segment.get("references", [])
                if not isinstance(references, list):
                    raise ValueError(f"references must be a list: {context}")
                if origin == "source_text" and not references:
                    raise ValueError(f"Source text requires a source reference: {context}")
                for reference in references:
                    _validate_reference(reference, source_map, context)
            visuals = point.get("visuals", [])
            if not isinstance(visuals, list):
                raise ValueError(f"visuals must be a list: {context}")
            for visual in visuals:
                _validate_visual(visual, source_map, context, require_confirmed)
            recall_lines = point.get("recall_lines", 0)
            if isinstance(recall_lines, bool) or not isinstance(recall_lines, int) or not 0 <= recall_lines <= 12:
                raise ValueError(f"recall_lines must be between 0 and 12: {context}")
    unknown_chapter_targets = sorted(
        target
        for target in {item["target"] for item in transformations}
        if target.startswith("chapter:") and target.removeprefix("chapter:") not in chapter_ids
    )
    if unknown_chapter_targets:
        raise ValueError(
            "Transformation target references an unknown chapter: "
            + ", ".join(unknown_chapter_targets)
        )
    review = project.get("review", {})
    if not isinstance(review, dict):
        raise ValueError("review must be an object")
    _reject_extra(review, {"status", "confirmed_at", "confirmed_by", "notes"}, "review")
    if review.get("status") not in {"draft", "confirmed"} or review.get("confirmed_by", "not_confirmed") not in {"user", "not_confirmed"}:
        raise ValueError("Invalid review status")
    if require_confirmed and (review.get("status") != "confirmed" or review.get("confirmed_by") != "user"):
        raise ValueError("The project must be explicitly confirmed by the user before generation.")
    if require_confirmed and not str(review.get("confirmed_at", "")).strip():
        raise ValueError("confirmed_at is required for a confirmed project")
    if review.get("confirmed_at") is not None:
        _datetime(review["confirmed_at"], "review.confirmed_at")


def _evidence_text(grading: dict[str, Any], sources: dict[str, dict[str, Any]]) -> str:
    def render(items: list[dict[str, Any]]) -> str:
        rendered = []
        for item in items:
            text = f"{item['kind']}: {item['statement']}（置信度 {float(item['confidence']):.0%}）"
            if item.get("reference"):
                text += f"；{source_label(item['reference'], sources)}"
            rendered.append(text)
        return "；".join(rendered)

    return (
        f"重要度依据：{render(grading['importance_evidence'])}；"
        f"R 依据：{render(grading['weakness_evidence'])}"
    )


def _visual_block(visual: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    kind = visual["type"]
    origin_label = ORIGIN_LABELS[visual["origin"]]
    source = "；".join(source_label(item, sources) for item in visual.get("references", []))
    if kind == "image":
        return {
            "type": "image", "path": visual["path"],
            "caption": f"{origin_label} · {visual.get('caption') or visual['title']}",
            "source": source, "origin_label": origin_label,
        }
    return {
        "type": kind,
        "title": visual["title"],
        "origin_label": origin_label,
        "source": source,
        "headers": visual.get("headers", []),
        "rows": visual.get("rows", []),
        "items": visual.get("items", []),
        "relations": visual.get("relations", []),
    }


def to_print_manifest(project: dict[str, Any], profile: str) -> dict[str, Any]:
    if profile not in {"color", "bw"}:
        raise ValueError("profile must be color or bw")
    validate_project(project, require_confirmed=True)
    sources = {item["id"]: item for item in project["sources"]}
    sections = []
    for chapter in project["chapters"]:
        blocks = []
        for point in chapter["points"]:
            grading = point["grading"]
            fragments = []
            for segment in point["segments"]:
                references = [source_label(item, sources) for item in segment.get("references", [])]
                fragments.append({
                    "origin": segment["origin"],
                    "origin_label": ORIGIN_LABELS[segment["origin"]],
                    "text": segment["content"],
                    "verbatim": bool(segment.get("verbatim")),
                    "source": "；".join(references),
                })
            blocks.append({
                "type": "knowledge_point",
                "id": point["id"],
                "title": point["title"],
                "importance": grading["importance"],
                "personal_weak": grading["personal_weak"],
                "grading_evidence": _evidence_text(grading, sources),
                "segments": fragments,
            })
            blocks.extend(_visual_block(item, sources) for item in point.get("visuals", []))
            if point.get("recall_lines", 0):
                blocks.append({"type": "recall", "label": "主动回忆", "lines": point["recall_lines"]})
        sections.append({"id": chapter["id"], "title": chapter["title"], "blocks": blocks})
    return {
        "mode": "memorization",
        "title": project["title"],
        "subject": project["subject"],
        "chapter": project.get("scope") or "多章节背诵材料",
        "print_profile": profile,
        "density": project.get("density", "standard"),
        "include_toc": len(sections) > 1,
        "source_label": "；".join(item["label"] for item in project["sources"]),
        "sections": sections,
    }
