---
name: kaoyan-question-builder
description: "Build print-ready Chinese exam question sets from one or more PDFs through a local visual workflow: detect question boundaries cheaply, let the user select and correct regions, run high-precision vision only on selected questions, reconstruct editable text and necessary diagrams, review uncertainties and answer leakage, then export an A4 PDF. Use when users need to extract, reorder, proofread, or combine questions from PDFs rather than paste whole-question screenshots."
---

# Kaoyan Question Builder

Reconstruct selected questions from PDFs without inventing unreadable content or treating the tool as an autonomous study planner. Reuse kaoyan-print-kit for PDF/DOCX layout and final QA.

## Run The Workflow

1. Read references/workflow.md, references/project-schema.json, and references/qa.md. Read references/high-precision-response.schema.json before recognition.
2. Start the local UI with python scripts/serve.py; keep it on loopback unless the user explicitly requests LAN access.
3. Upload PDFs in the UI. Treat detected boxes as candidates, not verified questions.
4. Let the user select, resize, merge, split, link, and reorder candidates. Preserve PDF, page, bbox, source order, and recognized book page.
5. Run high-precision vision only on selected candidates. If the provider is unavailable, use manual transcription.
6. Compare every source crop with reconstructed content. Require confirmation for low-confidence fragments, formula uncertainty, missing subquestions, necessary graphics, and suspected answer leakage.
7. Export PDF only after references/qa.md has no blockers. Default to A4 black-and-white, source order, original numbering, source labels, and answer space.
8. Ask whether to retain the full project, only the final PDF, or nothing. Do not move session data into projects/ without explicit authorization.

## Configure Vision

Read references/provider.md. Read API keys only from the configured environment variable. Never place a key in repository files, request bodies, frontend code, or logs.

## Reuse The Print Layer

Convert reviewed questions into the existing print-kit question blocks. Keep ordinary text, options, subquestions, formulas, and simple tables as selectable text. Crop only necessary geometry, function, statistics, circuit, or complex data figures as separate images. Never paste a whole question screenshot into the final PDF.

## Stop Conditions

- Stop for manual correction when the source has no reliable text layer, question numbering is ambiguous, a cross-page relation is uncertain, or OCR cannot preserve a formula.
- Block export when any selected question lacks a reviewed stem, has unresolved uncertainty, may omit a subquestion, or has unreviewed answer leakage.
- Do not claim automatic formula OCR, cross-page detection, or graphic extraction succeeded unless the source and reconstructed result were actually compared.
