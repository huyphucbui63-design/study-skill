# Content And Provenance Contract

## Ordering

- Preserve source file order, chapter order, and knowledge-point order by default.
- Treat A/B/C and R as annotations, never sort keys.
- Store a positive `source_order` on every source, chapter, and knowledge point. Keep arrays in ascending source order.
- Merge, regroup, rewrite, or reorder only after an explicit user request. Record a structured `transformations` entry with `authorized_by: user`, authorization time, details, and an exact `target`: `sources`, `chapters`, or `chapter:<chapter-id>`. Authorization for one target never permits reordering another array.

## Origin Types

Every content segment and every visual structure has exactly one origin.

| Origin | Meaning | Editing rule |
| --- | --- | --- |
| `source_text` | Verbatim or verified source material | Preserve exact definitions, theorem conditions, formulas, and terminology |
| `ai_summary` | Model-authored compression | Label visibly; never substitute it for an exact definition |
| `ai_memory_aid` | Mnemonic, recall cue, or analogy | Label visibly and keep removable |
| `ai_example` | Model-authored example | Label visibly; verify facts and boundary conditions |
| `user_note` | User supplement or wording | Preserve verbatim; do not silently polish |

Use `verbatim: true` only for checked source text or an explicitly verbatim user note. A segment with uncertain characters, formulas, or page mapping must set `needs_review: true` and include an uncertainty note.

## Source References

Assign every source-derived segment one or more references. A reference identifies `source_id` and the narrowest available locator: PDF page, original book page, DOCX paragraph/heading, image name, or text range. PDF pages are one-based file pages, not assumed printed page numbers.

For file-backed sources, retain the project-relative or absolute path and record SHA-256 when available. Generation must fail when a referenced file is missing or its recorded hash no longer matches. Inline conversation text uses an empty path and cannot claim a file hash.

AI-authored content should cite the source material it derives from when possible but must remain AI-labeled. User notes may omit a source reference.

Comparison tables, processes, timelines, relationships, and images follow the same rule. A source-derived visual requires a source reference; an AI-authored visual keeps an explicit AI label in both PDF and DOCX output.

## Extraction Boundaries

- Use PDF text extraction for selectable text and visual inspection for layout. Treat broken formula extraction as unresolved.
- Extract DOCX paragraphs and tables in document order. Do not treat headers, footers, comments, or tracked changes as accepted source content without inspection.
- For images, transcribe conservatively. Preserve formulas or diagrams as images when reliable transcription is unavailable.
- Do not guess missing definitions, symbols, table cells, dates, or relationships.

## Confirmation Gate

Before final generation, show the user the ordered outline, labels, evidence, origin labels, and unresolved fragments. Only explicit confirmation may set `review.status` to `confirmed`; a model cannot self-confirm.
