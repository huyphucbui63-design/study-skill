from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "kaoyan-strategy-advisor"
SCRIPT = SKILL_DIR / "scripts" / "strategy_store.py"
SPEC = importlib.util.spec_from_file_location("strategy_store", SCRIPT)
assert SPEC and SPEC.loader
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)


def sample_journey(day: str = "2026-08-07") -> dict:
    return {
        "date": day,
        "target": "数学保持稳定，专业课提高回忆质量",
        "stage": "强化阶段",
        "subject_progress": {"数学": "用户原话：完成两章", "专业课": "用户原话：刚开始第二轮"},
        "study_state": "最近容易疲劳，但仍能完成复盘",
        "main_problems": ["专业课回忆证据不足"],
        "constraints": ["工作日可用时间有限"],
        "ideas": ["想尝试先调整活动比例"],
        "important_decisions": ["暂不制定每日任务"],
    }


def sample_analysis() -> dict:
    return {
        "status_snapshot": {
            "as_of": "2026-08-07",
            "stage": "强化阶段",
            "summary": "数学状态较稳定；专业课检测证据不足。",
            "source_refs": ["current_question", "journey.latest:2026-08-07"],
        },
        "user_question": "各科投入比例需要调整吗？",
        "analysis_summary": "建议先做小幅、可逆调整。",
        "recommendations": [
            {
                "recommendation_id": "rec_ratio",
                "category": "subject_allocation",
                "suggestion": "专业课投入占比小幅上调，数学保持区间。",
                "evidence_refs": ["current_question", "journey.latest:2026-08-07"],
                "confidence": "medium",
                "confidence_reason": "有直接状态描述，但缺少检测数据。",
                "information_gaps": ["近两周专业课回忆正确率"],
                "costs": ["会挤压其他科目的时间"],
                "review_window": "7-14 天",
                "review_at": "2026-08-21",
                "review_conditions": ["得到两次可比的回忆结果"],
                "fallbacks": ["只替换低收益的被动阅读时段"],
            }
        ],
    }


class StrategyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name) / "data"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_context_is_read_only_and_preserves_priority(self) -> None:
        result = store.build_context(self.data_dir, "本次问题原文")
        self.assertEqual(result["current_question"], "本次问题原文")
        self.assertEqual(
            result["evidence_priority"],
            ["current_question", "journey.latest", "journey.history", "confirmed_study_records", "strategy_history"],
        )
        self.assertFalse(self.data_dir.exists())

    def test_every_write_requires_operation_scoped_authorization(self) -> None:
        with self.assertRaises(store.DataError):
            store.init_data(self.data_dir, authorized=False)
        with self.assertRaises(store.DataError):
            store.append_journey(self.data_dir, sample_journey(), authorized=False)
        with self.assertRaises(store.DataError):
            store.save_analysis(self.data_dir, sample_analysis(), "keep_accepted", authorized=False)
        self.assertFalse(self.data_dir.exists())

    def test_journey_is_append_only_and_keeps_user_wording(self) -> None:
        first = store.append_journey(self.data_dir, sample_journey(), authorized=True)
        before = (self.data_dir / "kaoyan-journey.md").read_text(encoding="utf-8")
        correction = sample_journey("2026-08-08")
        correction["study_state"] = "用户更正：昨天并不疲劳"
        correction["correction_of"] = first["entry_id"]
        second = store.append_journey(self.data_dir, correction, authorized=True)
        after = (self.data_dir / "kaoyan-journey.md").read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))
        self.assertIn("用户原话：完成两章", after)
        self.assertIn("用户更正：昨天并不疲劳", after)
        parsed = store.read_journey(self.data_dir / "kaoyan-journey.md")
        self.assertEqual(len(parsed["history"]), 2)
        self.assertEqual(parsed["latest"]["entry_id"], second["entry_id"])

    def test_manual_journey_headings_are_read_without_reformatting(self) -> None:
        self.data_dir.mkdir()
        path = self.data_dir / "kaoyan-journey.md"
        original = "# 我的历程\n\n## 2026-08-01\n\n这是我自己写的原话。\n\n## 2026-08-03\n\n阶段变化。\n"
        path.write_text(original, encoding="utf-8")
        parsed = store.read_journey(path)
        self.assertEqual(parsed["raw_markdown"], original)
        self.assertEqual(parsed["latest"]["date"], "2026-08-03")

    def test_only_explicitly_retained_study_records_are_visible(self) -> None:
        self.data_dir.mkdir()
        rows = [
            {
                "record_id": "full", "event_type": "study_record", "date": "2026-08-01",
                "user_self_summary": "完整记录总结原文", "ai_observations": ["AI 观察"], "image_refs": ["private.jpg"],
                "save_authorization": {"confirmed": True, "choice": "keep_full", "authorized_at": "2026-08-01T10:00:00Z"},
            },
            {
                "record_id": "summary", "event_type": "study_record", "date": "2026-08-02",
                "user_self_summary": "只保留总结原文", "ai_observations": ["不应暴露"], "image_refs": ["private2.jpg"],
                "save_authorization": {"confirmed": True, "choice": "keep_summary", "authorized_at": "2026-08-02T10:00:00Z"},
            },
            {
                "record_id": "draft", "event_type": "study_record", "status": "draft",
                "save_authorization": {"confirmed": True, "choice": "keep_full", "authorized_at": "2026-08-02T10:00:00Z"},
            },
            {
                "record_id": "unconfirmed", "event_type": "study_record",
                "save_authorization": {"confirmed": False, "choice": "keep_full", "authorized_at": None},
            },
        ]
        path = self.data_dir / "study-records.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        visible = store.confirmed_study_records(path)
        self.assertEqual([row["record_id"] for row in visible], ["full", "summary"])
        self.assertIn("ai_observations", visible[0])
        self.assertEqual(visible[1]["user_self_summary"], "只保留总结原文")
        self.assertNotIn("ai_observations", visible[1])
        self.assertNotIn("image_refs", visible[1])

    def test_retention_choices_and_decisions_are_append_only(self) -> None:
        self.assertEqual(store.save_analysis(self.data_dir, sample_analysis(), "no_save", False)["saved"], False)
        self.assertFalse(self.data_dir.exists())
        state = store.save_analysis(self.data_dir, sample_analysis(), "analysis_only", True)
        self.assertEqual(state["events_appended"], 1)
        events = store.read_jsonl(self.data_dir / "strategy-history.jsonl")
        self.assertEqual(events[0]["event_type"], "strategy_state_analysis")
        self.assertNotIn("recommendations", events[0])
        saved = store.save_analysis(self.data_dir, sample_analysis(), "keep_undecided", True)
        self.assertEqual(saved["events_appended"], 2)
        context = store.build_context(self.data_dir, "复评")
        key = f"{saved['analysis_id']}:rec_ratio"
        self.assertEqual(context["current_recommendation_decisions"][key]["status"], "undecided")
        store.append_decision(self.data_dir, saved["analysis_id"], "rec_ratio", "accepted", None, True)
        context = store.build_context(self.data_dir, "复评")
        self.assertEqual(context["current_recommendation_decisions"][key]["status"], "accepted")
        lines = store.read_jsonl(self.data_dir / "strategy-history.jsonl")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[-2]["decision_status"], "undecided")
        self.assertEqual(lines[-1]["decision_status"], "accepted")

    def test_keep_accepted_marks_only_explicit_choice(self) -> None:
        saved = store.save_analysis(self.data_dir, sample_analysis(), "keep_accepted", True)
        events = store.read_jsonl(self.data_dir / "strategy-history.jsonl")
        self.assertEqual(events[0]["recommendations"][0]["decision_status"], "proposed")
        self.assertEqual(events[1]["decision_status"], "accepted")
        self.assertEqual(events[1]["analysis_id"], saved["analysis_id"])

    def test_malformed_jsonl_is_blocking_with_line_number(self) -> None:
        self.data_dir.mkdir()
        path = self.data_dir / "strategy-history.jsonl"
        path.write_text('{}\n{"broken"\n', encoding="utf-8")
        with self.assertRaisesRegex(store.DataError, r":2:"):
            store.read_jsonl(path)

    def test_cli_no_save_does_not_create_history(self) -> None:
        source = Path(self.temp.name) / "analysis.json"
        source.write_text(json.dumps(sample_analysis(), ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "save-analysis", "--data-dir", str(self.data_dir),
             "--input", str(source), "--choice", "no_save"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse((self.data_dir / "strategy-history.jsonl").exists())

    def test_schema_files_parse_and_match_example(self) -> None:
        schema_dir = SKILL_DIR / "schemas"
        schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in schema_dir.glob("*.schema.json")
        }
        self.assertIn("strategy-analysis-input.schema.json", schemas)
        self.assertIn("strategy-history.schema.json", schemas)
        self.assertEqual(schemas["strategy-analysis-input.schema.json"]["$schema"], "https://json-schema.org/draft/2020-12/schema")
        example = json.loads((SKILL_DIR / "references" / "example-analysis.json").read_text(encoding="utf-8"))
        validated = store.validate_analysis(example)
        self.assertEqual(validated["recommendations"][0]["decision_status"], "proposed")


if __name__ == "__main__":
    unittest.main()
