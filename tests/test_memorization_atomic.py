from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "kaoyan-memorization-builder"


def confirmed_project(source: Path) -> dict:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    user_evidence = [{
        "kind": "user_designation",
        "statement": "The user confirmed this marker.",
        "confidence": 1.0,
    }]
    return {
        "schema_version": "1.0",
        "title": "Atomic generation fixture",
        "subject": "Math",
        "sources": [{
            "id": "s1",
            "source_order": 1,
            "type": "user_text",
            "label": source.name,
            "path": source.name,
            "sha256": digest,
        }],
        "chapters": [{
            "id": "c1",
            "source_order": 1,
            "title": "Chapter",
            "points": [{
                "id": "p1",
                "source_order": 1,
                "title": "Definition",
                "grading": {
                    "importance": "A",
                    "importance_status": "confirmed",
                    "importance_evidence": user_evidence,
                    "personal_weak": False,
                    "weakness_status": "confirmed",
                    "weakness_evidence": user_evidence,
                },
                "segments": [{
                    "origin": "source_text",
                    "content": "Verified source text.",
                    "verbatim": True,
                    "needs_review": False,
                    "references": [{"source_id": "s1", "text_range": "all"}],
                }],
            }],
        }],
        "transformations": [],
        "review": {
            "status": "confirmed",
            "confirmed_at": "2026-08-07T00:00:00+08:00",
            "confirmed_by": "user",
        },
    }


class AtomicPublishingTests(unittest.TestCase):
    def test_empty_generator_payload_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.txt"
            source.write_text("Verified source text.", encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps(confirmed_project(source)), encoding="utf-8")
            fake_generator = root / "fake_generator.py"
            fake_generator.write_text(
                "import json\nprint(json.dumps({'generated': []}))\n",
                encoding="utf-8",
            )
            output = root / "out"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL / "scripts" / "build_memorization.py"),
                    str(project),
                    "--output-dir",
                    str(output),
                    "--print-kit-script",
                    str(fake_generator),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one PDF and one DOCX", result.stderr)
            self.assertFalse(output.exists())

    def test_corrupt_generator_files_publish_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.txt"
            source.write_text("Verified source text.", encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps(confirmed_project(source)), encoding="utf-8")
            fake_generator = root / "fake_generator.py"
            fake_generator.write_text(
                """import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('manifest')
parser.add_argument('--output-dir', required=True)
parser.add_argument('--variants')
args = parser.parse_args()
output = Path(args.output_dir)
output.mkdir(parents=True, exist_ok=True)
pdf = output / 'bad.pdf'
docx = output / 'bad.docx'
pdf.write_bytes(b'not a pdf')
docx.write_bytes(b'not a docx')
print(json.dumps({'generated': [str(pdf), str(docx)]}))
""",
                encoding="utf-8",
            )
            output = root / "out"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL / "scripts" / "build_memorization.py"),
                    str(project),
                    "--output-dir",
                    str(output),
                    "--print-kit-script",
                    str(fake_generator),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unreadable PDF", result.stderr)
            self.assertFalse(output.exists())

    def test_changed_source_is_rejected_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.txt"
            source.write_text("Original source.", encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps(confirmed_project(source)), encoding="utf-8")
            source.write_text("Changed after confirmation.", encoding="utf-8")
            output = root / "out"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL / "scripts" / "build_memorization.py"),
                    str(project),
                    "--output-dir",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Source sha256 mismatch", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
