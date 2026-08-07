#!/usr/bin/env python3
"""Read and append consented kaoyan journey and strategy history data."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CHOICES = {"keep_accepted", "keep_undecided", "analysis_only", "no_save"}
DECISIONS = {"accepted", "rejected", "undecided"}
CATEGORIES = {
    "stage_direction", "subject_allocation", "activity_allocation",
    "progress_risk", "stage_switch", "observation_window", "fallback",
}
JOURNEY_START = "<!-- KAOYAN_JOURNEY_ENTRY_START"
JOURNEY_END = "<!-- KAOYAN_JOURNEY_ENTRY_END -->"
JOURNEY_HEADER = """# 考研历程

> 本文件由用户维护并按日期追加。AI 仅可在用户明确要求时追加用户提供的内容，不得重写历史或把推断写成用户观点。

"""


class DataError(ValueError):
    """Persisted or proposed data is unsafe or invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def require_authorization(authorized: bool) -> None:
    if not authorized:
        raise DataError("Refusing to write without explicit --authorize-write for this operation.")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"Could not read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DataError(f"JSON input must be one object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DataError(f"Could not read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataError(f"Malformed JSONL at {path}:{line_number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise DataError(f"Malformed JSONL at {path}:{line_number}: expected one object")
        result.append(value)
    return result


def append_jsonl(path: Path, values: Iterable[dict[str, Any]], authorized: bool) -> None:
    require_authorization(authorized)
    rows = list(values)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.exists() and path.stat().st_size:
        with path.open("rb") as check:
            check.seek(-1, os.SEEK_END)
            prefix = "\n" if check.read(1) != b"\n" else ""
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(prefix)
        for value in rows:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def parse_date(value: Any, field: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise DataError(f"{field} must be an ISO date string")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise DataError(f"{field} must use YYYY-MM-DD") from exc
    return value


def require_string(value: Any, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "" if allow_empty else " non-empty"
        raise DataError(f"{field} must be a{qualifier} string")
    return value


def require_string_list(value: Any, field: str, min_items: int = 0) -> list[str]:
    valid = isinstance(value, list) and len(value) >= min_items and all(isinstance(item, str) for item in value)
    if not valid:
        raise DataError(f"{field} must be a list of strings with at least {min_items} item(s)")
    return value


def validate_journey_entry(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "date", "target", "stage", "subject_progress", "study_state",
        "main_problems", "constraints", "ideas", "important_decisions", "correction_of",
    }
    required = allowed - {"correction_of"}
    if set(value) - allowed or required - set(value):
        raise DataError(f"Journey fields must be {sorted(required)} plus optional correction_of")
    parse_date(value["date"], "date")
    for field in ("target", "stage", "study_state"):
        require_string(value[field], field, allow_empty=True)
    progress = value["subject_progress"]
    if not isinstance(progress, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in progress.items()):
        raise DataError("subject_progress must be an object of exact user strings")
    for field in ("main_problems", "constraints", "ideas", "important_decisions"):
        require_string_list(value[field], field)
    if value.get("correction_of") is not None:
        require_string(value["correction_of"], "correction_of")
    return copy.deepcopy(value)


def markdown_list(items: list[str]) -> list[str]:
    return [f"  - {item}" for item in items] or ["  - （未提供）"]


def render_journey_entry(entry: dict[str, Any], entry_id: str) -> str:
    lines = [
        f'{JOURNEY_START} id="{entry_id}" -->', f"## {entry['date']}", "",
        "- 输入来源：用户", f"- 记录 ID：{entry_id}", f"- 目标：{entry['target']}",
        f"- 阶段：{entry['stage']}", "- 各科进度：",
    ]
    progress = [f"  - {subject}：{text}" for subject, text in entry["subject_progress"].items()]
    lines.extend(progress or ["  - （未提供）"])
    lines.extend([f"- 学习状态：{entry['study_state']}", "- 主要问题："])
    lines.extend(markdown_list(entry["main_problems"]))
    for label, field in (("约束", "constraints"), ("想法", "ideas"), ("重要决策", "important_decisions")):
        lines.append(f"- {label}：")
        lines.extend(markdown_list(entry[field]))
    if entry.get("correction_of"):
        lines.append(f"- 更正对象：{entry['correction_of']}")
    lines.extend([JOURNEY_END, ""])
    return "\n".join(lines)


def init_data(data_dir: Path, authorized: bool) -> dict[str, Any]:
    require_authorization(authorized)
    journey = data_dir / "kaoyan-journey.md"
    if journey.exists():
        return {"created": False, "path": str(journey)}
    data_dir.mkdir(parents=True, exist_ok=True)
    journey.write_text(JOURNEY_HEADER, encoding="utf-8", newline="\n")
    return {"created": True, "path": str(journey)}


def append_journey(data_dir: Path, entry: dict[str, Any], authorized: bool) -> dict[str, Any]:
    require_authorization(authorized)
    entry = validate_journey_entry(entry)
    journey = data_dir / "kaoyan-journey.md"
    data_dir.mkdir(parents=True, exist_ok=True)
    if not journey.exists():
        journey.write_text(JOURNEY_HEADER, encoding="utf-8", newline="\n")
    entry_id = new_id("journey")
    with journey.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(render_journey_entry(entry, entry_id))
        stream.flush()
        os.fsync(stream.fileno())
    return {"entry_id": entry_id, "path": str(journey), "input_origin": "user"}


def read_journey(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "latest": None, "history": [], "raw_markdown": None}
    raw = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^##\s+(\d{4}-\d{2}-\d{2})\s*$\s*(.*?)(?=^##\s+\d{4}-\d{2}-\d{2}\s*$|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    entries: list[dict[str, Any]] = []
    for index, (entry_date, block) in enumerate(pattern.findall(raw), 1):
        id_match = re.search(r"^- 记录 ID：([^\r\n]+)$", block, re.MULTILINE)
        entries.append({
            "entry_id": id_match.group(1).strip() if id_match else f"manual_{entry_date}_{index}",
            "date": entry_date, "raw_markdown": f"## {entry_date}\n{block}".strip(),
            "input_origin": "user",
        })
    ordered = sorted(entries, key=lambda item: (item["date"] or "", item["entry_id"]))
    return {"exists": True, "latest": ordered[-1] if ordered else None, "history": ordered, "raw_markdown": raw}


def authorization_of(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("save_authorization")
    return value if isinstance(value, dict) else {}


def is_confirmed_study_record(record: dict[str, Any]) -> bool:
    auth = authorization_of(record)
    event_type = record.get("event_type") or record.get("record_type") or "study_record"
    formal = event_type in {"study_record", "study_record_correction", "correction"} and record.get("status") != "draft"
    return bool(
        formal and auth.get("confirmed") is True
        and auth.get("choice") in {"keep_full", "keep_summary", "keep_full_record", "keep_summary_only"}
        and auth.get("authorized_at")
    )


def summary_view(record: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version", "event_type", "record_type", "record_id", "correction_of",
        "date", "subject", "chapter", "scope", "material_name", "pages",
        "question_count", "error_count", "uncertain_count", "duration_minutes",
        "user_summary", "user_self_summary", "save_authorization",
    }
    return {key: copy.deepcopy(value) for key, value in record.items() if key in allowed}


def confirmed_study_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for record in read_jsonl(path):
        if not is_confirmed_study_record(record):
            continue
        choice = authorization_of(record).get("choice")
        records.append(summary_view(record) if choice in {"keep_summary", "keep_summary_only"} else record)
    return records


def validate_recommendation(value: dict[str, Any], index: int) -> dict[str, Any]:
    required = {
        "recommendation_id", "category", "suggestion", "evidence_refs", "confidence",
        "confidence_reason", "information_gaps", "costs", "review_window", "review_at",
        "review_conditions", "fallbacks",
    }
    if set(value) != required:
        raise DataError(f"recommendations[{index}] fields must be exactly {sorted(required)}")
    rec_id = require_string(value["recommendation_id"], f"recommendations[{index}].recommendation_id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", rec_id):
        raise DataError(f"recommendations[{index}].recommendation_id is invalid")
    if value["category"] not in CATEGORIES:
        raise DataError(f"recommendations[{index}].category is outside the stage-strategy boundary")
    require_string(value["suggestion"], f"recommendations[{index}].suggestion")
    require_string_list(value["evidence_refs"], f"recommendations[{index}].evidence_refs", 1)
    if value["confidence"] not in {"low", "medium", "high"}:
        raise DataError(f"recommendations[{index}].confidence is invalid")
    require_string(value["confidence_reason"], f"recommendations[{index}].confidence_reason")
    require_string_list(value["information_gaps"], f"recommendations[{index}].information_gaps")
    for field in ("costs", "review_conditions", "fallbacks"):
        require_string_list(value[field], f"recommendations[{index}].{field}", 1)
    require_string(value["review_window"], f"recommendations[{index}].review_window")
    parse_date(value["review_at"], f"recommendations[{index}].review_at", allow_none=True)
    result = copy.deepcopy(value)
    result["decision_status"] = "proposed"
    return result


def validate_analysis(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"status_snapshot", "user_question", "analysis_summary", "recommendations"}:
        raise DataError("Analysis input has unsupported or missing top-level fields")
    snapshot = value["status_snapshot"]
    if not isinstance(snapshot, dict) or not {"as_of", "summary", "source_refs"}.issubset(snapshot):
        raise DataError("status_snapshot requires as_of, summary, and source_refs")
    parse_date(snapshot["as_of"], "status_snapshot.as_of")
    require_string(snapshot["summary"], "status_snapshot.summary")
    require_string_list(snapshot["source_refs"], "status_snapshot.source_refs")
    require_string(value["user_question"], "user_question")
    require_string(value["analysis_summary"], "analysis_summary")
    if not isinstance(value["recommendations"], list):
        raise DataError("recommendations must be a list")
    recommendations: list[dict[str, Any]] = []
    for index, item in enumerate(value["recommendations"]):
        if not isinstance(item, dict):
            raise DataError(f"recommendations[{index}] must be an object")
        recommendations.append(validate_recommendation(item, index))
    ids = [item["recommendation_id"] for item in recommendations]
    if len(ids) != len(set(ids)):
        raise DataError("recommendation_id values must be unique within an analysis")
    result = copy.deepcopy(value)
    result["recommendations"] = recommendations
    return result


def strategy_paths(data_dir: Path) -> tuple[Path, Path, Path]:
    return data_dir / "kaoyan-journey.md", data_dir / "study-records.jsonl", data_dir / "strategy-history.jsonl"


def decision_state(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    current: dict[str, dict[str, Any]] = {}
    for event in history:
        if event.get("event_type") == "strategy_analysis":
            for rec in event.get("recommendations", []):
                if isinstance(rec, dict) and rec.get("recommendation_id"):
                    key = f"{event.get('analysis_id')}:{rec['recommendation_id']}"
                    current[key] = {"status": "proposed", "at": event.get("created_at"), "review_at": rec.get("review_at")}
        elif event.get("event_type") == "strategy_decision":
            key = f"{event.get('analysis_id')}:{event.get('recommendation_id')}"
            current[key] = {"status": event.get("decision_status"), "at": event.get("decided_at"), "review_at": event.get("review_at")}
    return current


def build_context(data_dir: Path, question: str) -> dict[str, Any]:
    journey_path, records_path, history_path = strategy_paths(data_dir)
    history = read_jsonl(history_path)
    return {
        "evidence_priority": ["current_question", "journey.latest", "journey.history", "confirmed_study_records", "strategy_history"],
        "current_question": question,
        "journey": read_journey(journey_path),
        "confirmed_study_records": confirmed_study_records(records_path),
        "strategy_history": history,
        "current_recommendation_decisions": decision_state(history),
        "warnings": ["Only explicitly retained study records are included. Proposed or undecided advice is not an adopted plan."],
    }


def save_analysis(data_dir: Path, value: dict[str, Any], choice: str, authorized: bool) -> dict[str, Any]:
    if choice not in CHOICES:
        raise DataError(f"Unknown retention choice: {choice}")
    if choice == "no_save":
        return {"saved": False, "choice": choice}
    require_authorization(authorized)
    analysis = validate_analysis(value)
    now = utc_now()
    analysis_id = new_id("analysis")
    event_type = "strategy_state_analysis" if choice == "analysis_only" else "strategy_analysis"
    main_event: dict[str, Any] = {
        "schema_version": "1.0", "event_id": new_id("event"), "event_type": event_type,
        "created_at": now, "analysis_id": analysis_id, "status_snapshot": analysis["status_snapshot"],
        "user_question": analysis["user_question"], "analysis_summary": analysis["analysis_summary"],
        "save_authorization": {"confirmed": True, "choice": choice, "authorized_at": now},
    }
    events = [main_event]
    if choice != "analysis_only":
        main_event["recommendations"] = analysis["recommendations"]
        status = "accepted" if choice == "keep_accepted" else "undecided"
        for rec in analysis["recommendations"]:
            events.append({
                "schema_version": "1.0", "event_id": new_id("event"),
                "event_type": "strategy_decision", "created_at": now, "analysis_id": analysis_id,
                "recommendation_id": rec["recommendation_id"], "decision_status": status,
                "decided_at": now, "review_at": rec["review_at"],
            })
    _, _, history_path = strategy_paths(data_dir)
    append_jsonl(history_path, events, authorized=True)
    return {"saved": True, "choice": choice, "analysis_id": analysis_id, "events_appended": len(events)}


def append_decision(
    data_dir: Path, analysis_id: str, recommendation_id: str, status: str,
    review_at: str | None, authorized: bool,
) -> dict[str, Any]:
    require_authorization(authorized)
    if status not in DECISIONS:
        raise DataError(f"decision status must be one of {sorted(DECISIONS)}")
    parse_date(review_at, "review_at", allow_none=True)
    _, _, history_path = strategy_paths(data_dir)
    history = read_jsonl(history_path)
    matches = [event for event in history if event.get("event_type") == "strategy_analysis" and event.get("analysis_id") == analysis_id]
    if not matches:
        raise DataError(f"Unknown analysis_id: {analysis_id}")
    recommendation = next(
        (rec for rec in matches[-1].get("recommendations", []) if rec.get("recommendation_id") == recommendation_id),
        None,
    )
    if recommendation is None:
        raise DataError(f"Unknown recommendation_id {recommendation_id} in {analysis_id}")
    now = utc_now()
    event = {
        "schema_version": "1.0", "event_id": new_id("event"), "event_type": "strategy_decision",
        "created_at": now, "analysis_id": analysis_id, "recommendation_id": recommendation_id,
        "decision_status": status, "decided_at": now,
        "review_at": review_at if review_at is not None else recommendation.get("review_at"),
    }
    append_jsonl(history_path, [event], authorized=True)
    return {"saved": True, "event_id": event["event_id"], "decision_status": status}


def validate_data(data_dir: Path) -> dict[str, Any]:
    journey_path, records_path, history_path = strategy_paths(data_dir)
    records = read_jsonl(records_path)
    history = read_jsonl(history_path)
    ids: set[str] = set()
    analyses: dict[str, set[str]] = {}
    for index, event in enumerate(history, 1):
        event_id = require_string(event.get("event_id"), f"strategy-history line {index} event_id")
        if event_id in ids:
            raise DataError(f"Duplicate strategy event_id at line {index}: {event_id}")
        ids.add(event_id)
        event_type = event.get("event_type")
        if event_type not in {"strategy_analysis", "strategy_state_analysis", "strategy_decision"}:
            raise DataError(f"Unsupported strategy event_type at line {index}: {event_type}")
        if event_type == "strategy_analysis":
            analyses[event.get("analysis_id")] = {
                rec.get("recommendation_id") for rec in event.get("recommendations", []) if isinstance(rec, dict)
            }
        elif event_type == "strategy_decision":
            analysis_id = event.get("analysis_id")
            if analysis_id not in analyses or event.get("recommendation_id") not in analyses[analysis_id]:
                raise DataError(f"Orphan strategy decision at line {index}")
    return {
        "valid": True, "journey_exists": journey_path.exists(), "study_record_lines": len(records),
        "confirmed_study_records": len(confirmed_study_records(records_path)), "strategy_event_lines": len(history),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--data-dir", type=Path, required=True)
    init.add_argument("--authorize-write", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--data-dir", type=Path, required=True)
    context = sub.add_parser("context")
    context.add_argument("--data-dir", type=Path, required=True)
    context.add_argument("--question", required=True)
    journey = sub.add_parser("append-journey")
    journey.add_argument("--data-dir", type=Path, required=True)
    journey.add_argument("--input", type=Path, required=True)
    journey.add_argument("--authorize-write", action="store_true")
    save = sub.add_parser("save-analysis")
    save.add_argument("--data-dir", type=Path, required=True)
    save.add_argument("--input", type=Path, required=True)
    save.add_argument("--choice", choices=sorted(CHOICES), required=True)
    save.add_argument("--authorize-write", action="store_true")
    decide = sub.add_parser("decide")
    decide.add_argument("--data-dir", type=Path, required=True)
    decide.add_argument("--analysis-id", required=True)
    decide.add_argument("--recommendation-id", required=True)
    decide.add_argument("--status", choices=sorted(DECISIONS), required=True)
    decide.add_argument("--review-at")
    decide.add_argument("--authorize-write", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "init":
            result = init_data(args.data_dir, args.authorize_write)
        elif args.command == "context":
            result = build_context(args.data_dir, args.question)
        elif args.command == "append-journey":
            result = append_journey(args.data_dir, load_json(args.input), args.authorize_write)
        elif args.command == "save-analysis":
            result = save_analysis(args.data_dir, load_json(args.input), args.choice, args.authorize_write)
        elif args.command == "decide":
            result = append_decision(
                args.data_dir, args.analysis_id, args.recommendation_id,
                args.status, args.review_at, args.authorize_write,
            )
        else:
            result = validate_data(args.data_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DataError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
