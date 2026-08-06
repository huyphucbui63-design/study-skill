# Mistake And Question Extraction Workflow

## Selection Methods

Accept page and question numbers, number ranges, chapter or keyword filters, user-provided lists, screenshots, or marked regions.

## Extraction

1. Render and inspect the relevant source pages before extraction.
2. Record original filename, page, and question number for every selected item.
3. Retype verified ordinary text. Preserve complex formulas and diagrams as cropped images.
4. Keep each question's stem, choices, diagram, answer, and explanation linked by a stable item ID.
5. Present the extraction list and uncertain fragments for confirmation before layout.

## Outputs

- `practice`: question, source, and writing space; never include answer clues.
- `answers`: question, answer, explanation, error cause, and related knowledge points.
- Generate both PDF and DOCX for both variants.

## Failure Conditions

Stop for confirmation when a requested question is missing, numbering is ambiguous, OCR differs from the source, a diagram is incomplete, or an answer cannot be linked confidently.

