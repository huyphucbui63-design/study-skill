from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "shared"),
    str(ROOT / "skills" / "kaoyan-question-builder" / "scripts"),
]

from kaoyan.project_store import ProjectStore, RevisionConflict
from kaoyan.provider import ProviderConfig, ProviderError, VisionProvider, parse_json_object
from qa_pdf import toc_findings
from question_builder.exporter import build_manifest, export_project, validate_for_export
from question_builder.pdf_pipeline import detect_boundaries, merge_candidates, split_candidate


def font_path() -> Path:
    choices = [
        Path("C:/Windows/Fonts/Deng.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    return next(path for path in choices if path.is_file())


def make_pdf(path: Path) -> None:
    pdfmetrics.registerFont(TTFont("TestCJK", str(font_path())))
    doc = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    doc.setFont("TestCJK", 12)
    doc.drawString(55, height - 70, "1. 求函数 f(x)=x^2 的导数。")
    doc.drawString(70, height - 100, "(1) 写出定义  (2) 计算结果")
    doc.drawString(55, height - 240, "2. 已知三角形 ABC，求角 A。")
    doc.drawString(55, 42, "12")
    doc.showPage()
    doc.setFont("TestCJK", 12)
    doc.drawString(55, height - 70, "3. 计算极限 lim x->0 sin(x)/x。")
    doc.drawString(55, height - 170, "答案：1")
    doc.drawString(55, 42, "13")
    doc.save()


class ProviderTests(unittest.TestCase):
    def test_config_rejects_secret_and_exposes_only_availability(self) -> None:
        with self.assertRaises(ValueError):
            ProviderConfig.from_mapping({"api_key": "secret"})
        with mock.patch.dict(os.environ, {"TEST_VISION_KEY": "secret"}, clear=False):
            value = ProviderConfig.from_mapping({"api_key_env": "TEST_VISION_KEY"}).public_dict()
        self.assertTrue(value["api_key_available"])
        self.assertNotIn("api_key", value)
        self.assertNotIn("secret", json.dumps(value))

    def test_environment_config_is_captured_explicitly(self) -> None:
        with mock.patch.dict(os.environ, {
            "KAOYAN_VISION_BASE_URL": "https://vision.example/v1",
            "KAOYAN_VISION_MODEL": "startup-model",
            "KAOYAN_VISION_API_KEY_ENV": "STARTUP_VISION_KEY",
            "STARTUP_VISION_KEY": "secret",
        }, clear=True):
            config = ProviderConfig.from_environment()
            self.assertEqual(config.base_url, "https://vision.example/v1")
            self.assertEqual(config.model, "startup-model")
            self.assertTrue(config.public_dict()["api_key_available"])
            mapped = ProviderConfig.from_mapping({})
            self.assertEqual(mapped.base_url, ProviderConfig.base_url)
            self.assertEqual(mapped.api_key_env, ProviderConfig.api_key_env)

    def test_base_url_rejects_embedded_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "credentials"):
            ProviderConfig.from_mapping({"base_url": "https://key@example.test/v1"})

    def test_provider_missing_key_allows_manual_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "x.png"
            image.write_bytes(b"not-needed")
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ProviderError, "manual transcription"):
                    VisionProvider(ProviderConfig(api_key_env="MISSING")).analyze([image], "x", "schema")

    def test_structured_json_parser(self) -> None:
        self.assertEqual(parse_json_object('{"stem":"x"}')["stem"], "x")
        with self.assertRaises(ProviderError):
            parse_json_object("stem=x")


class ProjectStoreTests(unittest.TestCase):
    def test_recovery_and_explicit_keep(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(Path(temp))
            project = store.create({"title": "sample", "candidates": []})
            self.assertEqual(store.list_projects()[0]["retention"], "session_only")
            kept = store.authorize_retention(project["project_id"], "keep_project")
            self.assertEqual(kept["retention"]["status"], "keep_project")
            self.assertTrue((Path(temp) / "projects" / "question-builder" / project["project_id"] / "project.json").is_file())

    def test_final_only_removes_private_intermediates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(Path(temp))
            project = store.create({"title": "sample", "candidates": []})
            folder = store.find_dir(project["project_id"])
            (folder / "sources").mkdir()
            (folder / "sources" / "private.pdf").write_bytes(b"private")
            (folder / "exports").mkdir()
            (folder / "exports" / "final.pdf").write_bytes(b"pdf")
            result = store.authorize_retention(project["project_id"], "final_pdf_only")
            self.assertEqual(result["kept_files"], ["final.pdf"])
            self.assertFalse(folder.exists())
            self.assertTrue((Path(temp) / "outputs" / "question-builder" / project["project_id"] / "final.pdf").is_file())

    def test_stale_revision_conflicts_and_deleted_project_is_not_resurrected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(Path(temp))
            project = store.create({"title": "sample", "candidates": []})
            stale = store.load(project["project_id"])
            current = store.load(project["project_id"])
            current["title"] = "new title"
            store.write(current, "title_changed")
            stale["title"] = "stale title"
            with self.assertRaises(RevisionConflict):
                store.write(stale, "stale_write")
            store.authorize_retention(project["project_id"], "discard_all", current["revision"])
            with self.assertRaises(FileNotFoundError):
                store.write(current, "resurrected")
            self.assertFalse((Path(temp) / "tmp" / "question-builder" / "sessions" / project["project_id"]).exists())

    def test_final_only_requires_a_staged_pdf_before_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ProjectStore(Path(temp))
            project = store.create({"title": "sample", "candidates": []})
            folder = store.find_dir(project["project_id"])
            (folder / "sources").mkdir()
            (folder / "sources" / "private.pdf").write_bytes(b"private")
            with self.assertRaisesRegex(ValueError, "exported PDF"):
                store.authorize_retention(project["project_id"], "final_pdf_only", project["revision"])
            self.assertTrue((folder / "sources" / "private.pdf").is_file())

            (folder / "exports").mkdir()
            (folder / "exports" / "final.pdf").write_bytes(b"pdf")
            with mock.patch("kaoyan.project_store.shutil.copy2", side_effect=OSError("copy failed")):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    store.authorize_retention(project["project_id"], "final_pdf_only", project["revision"])
            self.assertTrue((folder / "sources" / "private.pdf").is_file())


    def test_expired_session_drafts_are_removed_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.dict(os.environ, {"KAOYAN_SESSION_TTL_HOURS": "0"}, clear=False):
                store = ProjectStore(root)
            project = store.create({"title": "temporary", "candidates": []})
            folder = store.find_dir(project["project_id"])
            project_file = folder / "project.json"
            persisted = json.loads(project_file.read_text(encoding="utf-8"))
            persisted["updated_at"] = "2000-01-01T00:00:00+00:00"
            project_file.write_text(json.dumps(persisted), encoding="utf-8")

            with mock.patch.dict(os.environ, {"KAOYAN_SESSION_TTL_HOURS": "1"}, clear=False):
                ProjectStore(root)
            self.assertFalse(folder.exists())


class BoundaryTests(unittest.TestCase):
    def test_page_mapping_detection_merge_and_split(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "questions.pdf"
            make_pdf(source)
            candidates, pages = detect_boundaries(source)
            self.assertEqual([page["book_page"] for page in pages], ["12", "13"])
            self.assertEqual([item["question_number"] for item in candidates], ["1", "2", "3"])
            self.assertTrue(candidates[-1]["answer_suspect"])
            merged = merge_candidates(candidates, [candidates[0]["id"], candidates[1]["id"]])
            self.assertEqual(len(merged), 2)
            self.assertLessEqual(merged[0]["bbox"][1], candidates[0]["bbox"][1])
            self.assertGreaterEqual(merged[0]["bbox"][3], candidates[1]["bbox"][3])
            with self.assertRaisesRegex(ValueError, "cross-page linking"):
                merge_candidates(candidates, [candidates[0]["id"], candidates[-1]["id"]])
            split = split_candidate(merged, merged[0]["id"], 0.5)
            self.assertEqual(len(split), 3)
            split[0]["transcription"] = {"stem": "reviewed"}
            with self.assertRaises(ValueError):
                split_candidate(split, split[0]["id"], 0.5)
            with self.assertRaises(ValueError):
                merge_candidates(split, [split[0]["id"], split[1]["id"]])



class ExportTests(unittest.TestCase):
    def project(self) -> dict:
        return {
            "project_id": "test", "title": "合成题集", "subject": "数学", "chapter": "测试",
            "layout": {"numbering": "continuous", "answer_space_lines": 3},
            "candidates": [
                {
                    "id": "q1", "selected": True, "order": 1, "question_number": "8",
                    "source_file": "a.pdf", "pdf_page": 2, "source_pdf_page": 2, "book_page": "12",
                    "bbox": [0.1, 0.1, 0.9, 0.4], "confidence": .8, "answer_suspect": False,
                    "subquestions_detected": 1, "preserve_graphics": [],
                    "transcription": {
                        "stem": "求函数的导数。", "options": ["A. 1", "B. 2"], "subquestions": ["(1) 写定义"],
                        "tables": [{"headers": ["x", "f(x)"], "rows": [["0", "1"], ["1", "2"]]}],
                        "uncertainties": [], "uncertainties_confirmed": True,
                        "answer_leak_reviewed": True, "subquestions_confirmed": True, "chapter": "第一章",
                    },
                },
                {
                    "id": "q2", "selected": True, "order": 2, "question_number": "9",
                    "source_file": "b.pdf", "pdf_page": 3, "source_pdf_page": 1, "book_page": None,
                    "bbox": [0.1, 0.1, 0.9, 0.4], "confidence": .8, "answer_suspect": False,
                    "subquestions_detected": 0, "preserve_graphics": [],
                    "transcription": {
                        "stem": "计算极限。", "options": [], "subquestions": [],
                        "uncertainties": [], "uncertainties_confirmed": True,
                        "answer_leak_reviewed": True, "subquestions_confirmed": True, "chapter": "第二章",
                    },
                },
            ],
        }

    def test_export_gate(self) -> None:
        project = self.project()
        project["candidates"][0]["transcription"]["uncertainties"] = [{"fragment": "x", "reason": "blur", "confidence": .2}]
        project["candidates"][0]["transcription"]["uncertainties_confirmed"] = False
        self.assertTrue(validate_for_export(project))

    def test_provider_answer_leak_requires_review(self) -> None:
        project = self.project()
        transcription = project["candidates"][0]["transcription"]
        transcription["suspected_answer_leak"] = True
        transcription["answer_leak_reviewed"] = False
        self.assertTrue(validate_for_export(project))


    def test_source_page_mapping_and_toc(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = build_manifest(self.project(), Path(temp))
        self.assertTrue(manifest["include_toc"])
        first = manifest["sections"][0]["blocks"][0]
        second = manifest["sections"][1]["blocks"][0]
        self.assertIn("PDF 第 2 页", first["source"])
        self.assertIn("原书第 12 页", first["source"])
        self.assertIn("PDF 第 1 页", second["source"])
        self.assertEqual([first["number"], second["number"]], ["1", "2"])

    def test_cross_page_continuation_exports_as_one_question(self) -> None:
        project = self.project()
        project["candidates"][1]["relations"] = [{"type": "continuation_of", "candidate_id": "q1"}]
        with tempfile.TemporaryDirectory() as temp:
            manifest = build_manifest(project, Path(temp))
        blocks = [block for section in manifest["sections"] for block in section["blocks"]]
        self.assertEqual(len(blocks), 1)
        self.assertIn("求函数的导数", blocks[0]["stem"])
        self.assertIn("计算极限", blocks[0]["stem"])
        self.assertIn("a.pdf · PDF 第 2 页", blocks[0]["source"])
        self.assertIn("b.pdf · PDF 第 1 页", blocks[0]["source"])

    def test_real_pdf_export_has_text_toc_and_embedded_font(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            project = self.project()
            project["candidates"][0]["preserve_graphics"] = [[0.1, 0.1, 0.8, 0.8]]
            page_path = temp_path / "pages" / "page-2.png"
            page_path.parent.mkdir(parents=True)
            page = Image.new("RGB", (800, 1000), "white")
            draw = ImageDraw.Draw(page)
            draw.line((120, 600, 400, 180, 680, 600, 120, 600), fill="black", width=8)
            page.save(page_path)
            result = export_project(ROOT, project, temp_path)
            self.assertTrue(result["qa"]["passed"])
            pdf = PdfReader(result["pdf"])
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            text_by_page = [page.extract_text() or "" for page in pdf.pages]
            self.assertIn("目录", text)
            self.assertIn("求函数的导数", text)
            self.assertIn("f(x)", text)
            self.assertIn("a.pdf", text)
            image_count = 0
            fonts = []
            for page in pdf.pages:
                resources = page.get("/Resources", {})
                image_count += sum(1 for value in resources.get("/XObject", {}).values() if value.get_object().get("/Subtype") == "/Image")
                for font in resources.get("/Font", {}).values():
                    obj = font.get_object()
                    descriptor = obj.get("/FontDescriptor")
                    if descriptor:
                        desc = descriptor.get_object()
                        fonts.append(bool(desc.get("/FontFile") or desc.get("/FontFile2") or desc.get("/FontFile3")))
            self.assertTrue(any(fonts))
            self.assertGreaterEqual(image_count, 1)
            self.assertEqual(toc_findings(text_by_page, ["第一章", "第二章"]), [])

    def test_blank_graphic_blocks_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            project = self.project()
            project["candidates"][0]["preserve_graphics"] = [[0.1, 0.1, 0.8, 0.8]]
            page_path = temp_path / "pages" / "page-2.png"
            page_path.parent.mkdir(parents=True)
            Image.new("RGB", (800, 1000), "white").save(page_path)
            with self.assertRaisesRegex(ValueError, "必要图形框为空白"):
                export_project(ROOT, project, temp_path)


class SchemaTests(unittest.TestCase):
    def test_schemas_are_valid_json_with_required_fields(self) -> None:
        paths = [
            ROOT / "shared" / "schema" / "provider-config.schema.json",
            ROOT / "shared" / "schema" / "source-reference.schema.json",
            ROOT / "skills" / "kaoyan-question-builder" / "references" / "project-schema.json",
            ROOT / "skills" / "kaoyan-question-builder" / "references" / "high-precision-response.schema.json",
        ]
        for path in paths:
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")
        project_schema = json.loads(paths[2].read_text(encoding="utf-8"))
        self.assertIn("revision", project_schema["required"])
        response_schema = json.loads(paths[3].read_text(encoding="utf-8"))
        self.assertTrue({
            "stem", "options", "subquestions", "uncertainties", "suspected_answer_leak",
        }.issubset(response_schema["required"]))




if __name__ == "__main__":
    unittest.main()
