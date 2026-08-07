---
name: kaoyan-memorization-builder
description: Build traceable, print-ready Chinese exam memorization materials from PDF, DOCX, images, or user text. Use when Codex must select and grade knowledge points, preserve source order and exact definitions, distinguish source text from AI summaries/aids/examples and user notes, apply independent A/B/C importance and R weakness markers, and produce color plus grayscale-compatible PDF/DOCX study editions with recall space and visual memory structures.
---

# Kaoyan Memorization Builder

Create a reviewed knowledge-point project, then reuse the sibling `kaoyan-print-kit` generator for final PDF and DOCX layout. Do not create a second PDF/DOCX engine.

## Read Before Working

- Read `references/content-contract.md` before extracting or rewriting content.
- Read `references/grading-and-evidence.md` before assigning A/B/C or R.
- Read `references/layout-and-qa.md` before choosing visual structures or generating files.
- Validate project JSON against `schemas/memorization-project.schema.json`.

## Build The Reviewed Project

1. Collect the subject, requested scope, source authority, desired density, and source files or text. Preserve every source file.
2. Extract in source order. Record file, PDF page or DOCX paragraph/heading when available, original book page when known, and confidence. Never infer a missing formula or obscured phrase.
3. Create chapters and knowledge points in the same order as the user input or source. Add labels only. Do not regroup by importance, merge chapters, or rewrite an exact definition unless the user explicitly requests that transformation.
4. Store each content fragment as exactly one origin: `source_text`, `ai_summary`, `ai_memory_aid`, `ai_example`, or `user_note`. Preserve user notes verbatim.
5. Assign independent fields: `importance` plus `importance_status`/`importance_evidence`, and `personal_weak` (`true` means R) plus `weakness_status`/`weakness_evidence`. Keep each model-only judgment as `ai_suggestion` until the user confirms or corrects that marker.
6. Use comparison, process, timeline, or relationship visuals only when they reduce memory load. Keep the underlying facts in traceable text; do not hide essential content inside decorative graphics.
7. Show the proposed chapter/point order, exact-source fragments, AI-authored fragments, all A/B/C and R markers, evidence, and every uncertainty. Wait for explicit user confirmation before setting `review.status` to `confirmed`.

For deterministic initial extraction, run:

```powershell
python scripts/extract_sources.py --title <title> --subject <subject> --output <project.json> <source...>
```

Use repeatable `--text <verbatim-user-text>` when the source is supplied directly in the conversation rather than as a file.

Image-only pages and suspicious PDF text enter manual review; the extractor never claims formula OCR success.

## Generate Both Editions

Generate only from a confirmed project:

```powershell
python scripts/build_memorization.py <project.json> --output-dir <output-directory>
```

The command rechecks source paths and recorded SHA-256 hashes, then validates provenance, evidence, scoped reorder authorization, review status, and unresolved fragments. It validates both profiles in a temporary area before publishing content-equivalent `color-study.pdf/.docx` and `bw-study.pdf/.docx` through `kaoyan-print-kit`. Use `--print-kit-script` only when the sibling skill is installed elsewhere.

## Verify Before Delivery

1. Render every PDF page with Poppler and every DOCX page with the documents renderer. Inspect every rendered page at 100% zoom.
2. Run `scripts/qa_material.py` on both PDFs with `--min-image-dpi 150`. Pass each expected directory target as `--toc-entry "章节名=页码"`. Require selectable text, embedded nonstandard fonts, nonempty pages, required source labels, directory text, the chapter heading on that page, and a matching PDF bookmark target.
3. Run `scripts/qa_docx.py <color.docx> <bw.docx> --require-toc --min-image-dpi 150 --min-keep-next <count>` for multi-chapter material. Require content equivalence, East Asian font declarations, the DOCX directory field, measured image DPI, and knowledge-point title pagination markers.
4. Compare the color and black-and-white editions visually. Confirm A/B/C and R remain identifiable in grayscale through text labels, weight, borders, and structure.
5. Check formulas and symbols against the source, image sharpness, directory page numbers, clipping, overflow, awkward page breaks, and whether exact definitions changed.
6. Stop for manual correction when extraction, formula transcription, source authority, grading evidence, or image fidelity remains uncertain. Never describe an unverified path as successful.

Deliver the final PDF and DOCX editions. Keep project JSON and renders as working artifacts unless the user asks to retain them.
