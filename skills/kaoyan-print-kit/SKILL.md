---
name: kaoyan-print-kit
description: Create print-ready Chinese study materials as polished PDF and editable DOCX files. Use for exam memorization sheets, formula or definition collections, extracting and recombining selected questions from PDF/Word/images, wrong-question books, knowledge explanations, and diagnostic tests that check real understanding.
---

# Kaoyan Print Kit

Turn mixed study sources into accurate, printable learning materials. Reuse the bundled PDF and documents skills for source inspection, rendering, and visual QA.

## Start Every Task

1. Classify the request as `memorization`, `mistakes`, or `diagnostic`. Ask only when ambiguous.
2. Ask the user to choose `bw` or `color` for every run. Do not assume a print profile.
3. Collect the required subject, chapter, requested content type, source files, and selection rules.
4. Preserve source files. Store finals under the user's Documents folder at `考研资料/<category>/<subject>/<chapter>/<YYYY-MM-DD-title>/` unless the user specifies another location.
5. Create a JSON manifest that follows `references/manifest-schema.md`.
6. Show the proposed structure, selected source ranges, and every uncertain OCR fragment before generating files. Wait for approval.

## Route By Mode

- For `memorization`, read `references/memorization.md`.
- For `mistakes`, read `references/mistakes.md`.
- For `diagnostic`, read `references/diagnostics.md`.
- Always read `references/layout.md` before authoring the manifest.
- Always read `references/qa.md` before final review.

## Generate Drafts

Run the bundled generator with the Codex workspace Python runtime:

```powershell
python <skill-directory>/scripts/build_material.py <manifest.json> --output-dir <archive-directory>
```

The generator produces PDF and content-equivalent DOCX files. It creates `practice` and `answers` variants for mistakes and diagnostic materials, and a `study` variant for memorization materials unless variants are explicitly supplied.

## Preview And Finalize

1. Render every draft PDF to PNG with Poppler and every draft DOCX to PNG with the documents skill renderer.
2. Show representative rendered pages to the user and request approval before final delivery.
3. After approval, ask the `study_pdf_reviewer` custom agent to inspect the source selections, manifest, and every rendered page. If that agent is unavailable, perform the same read-only review from `references/qa.md`; when subagents are available, delegate this independent review to a read-only subagent.
4. Fix all blocking findings, regenerate both formats, and repeat the full render review. Do not deliver when OCR uncertainty, missing glyphs, clipped content, answer leakage, source mismatch, or question-answer mismatch remains.
5. Deliver only the final PDF and DOCX files. Keep manifests and rendered PNGs as internal working files.

## Accuracy Rules

- Prefer source fidelity over visual uniformity.
- Retype ordinary text only after verifying it against the source.
- Preserve complex formulas, geometry, circuit diagrams, charts, and uncertain OCR as cropped high-resolution images.
- Mark generated explanations separately from source-derived statements.
- Never invent missing question text, answers, definitions, formulas, or citations.
- Use unobtrusive source labels containing the original filename and page or item number.
