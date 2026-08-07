# Question Builder Workflow

## Data states

Keep these states distinct:

- source: immutable uploaded PDF and page images.
- candidate: low-cost boundary observation, never a full-text transcription.
- transcription: provider result or user-entered reconstruction.
- correction: user-confirmed changes and review flags.
- export: derived manifest, separate graphic crops, and final PDF.
- retention: explicit keep_project, final_pdf_only, or discard_all authorization.

Store every correction as an append-only event in project.json. A current value may change, but the audit event must show what field changed and when.

## Boundary phase

Use the PDF text layer to find question-number starts. Save source file, PDF page, detected book page, normalized bbox, question number, confidence, subquestion count, shared-stem flag, cross-page relations, and suspected answer signals. Do not OCR all text during this phase.

For a scanned or ambiguous page, create a low-confidence whole-page candidate that is unselected by default. Require the user to resize or split it. Never infer invisible boundaries.

## Selection phase

Preserve source PDF order, PDF page order, and vertical page order by default. Support page selection, bbox correction, merge, split, cross-page link, and final drag ordering. Let the user add normalized boxes for necessary data graphics.

## Recognition phase

Crop only selected candidates. Request structured JSON containing stem, options, subquestions, simple tables, uncertainties, suspected answer leakage, necessary graphic boxes, and optional chapter. Do not send unselected pages to the high-precision provider.

Manual transcription is a first-class fallback. Preserve empty or uncertain fragments for correction instead of guessing.

## Review phase

Show the source crop and reconstruction together. Highlight provider uncertainties, suspected answers, and detected-versus-transcribed subquestion mismatch. A user confirmation clears a blocker but must not erase the original provider warning.

## Export and retention

Use kaoyan-print-kit/scripts/build_material.py as the PDF layout authority. Include source filename, PDF page, and recognized book page on every question. Include a generated table of contents for multiple sections or sources. Export PDF by default.

After generation, offer exactly three retention actions:

1. Keep the complete project under projects/question-builder/project-id/.
2. Keep only final PDFs under outputs/question-builder/project-id/ and delete source copies, crops, provider responses, and intermediate images.
3. Delete the temporary project and all generated output.

Unretained session drafts stay in the ignored tmp directory only for crash recovery. The server removes drafts older than 24 hours on startup by default; set KAOYAN_SESSION_TTL_HOURS to another positive hour count, or to 0 only when the user explicitly needs manual cleanup.
