# Question Builder Quality Gate

Block export until all selected questions pass:

- Source filename, PDF page, optional book page, bbox, and order are present and correct.
- Stem, choices, subquestions, ordinary text, formulas, and simple tables are reconstructed as selectable text.
- No whole-question screenshot appears in the final PDF.
- Every necessary diagram is a separate, nonblank, sharp crop and remains with its stem when practical.
- All low-confidence fragments and formula symbols are confirmed against the source.
- Detected small-question count and reconstructed small-question count agree, or the user explicitly confirms the difference.
- Suspected answer regions are reviewed and no answer clue leaks into the practice PDF.
- A4 margins, answer space, numbering choice, source labels, page order, and chapter order match the project.
- Multi-section/source table-of-contents page numbers match actual pages.
- Every PDF page renders non-empty, body text is selectable, fonts are embedded, graphics remain visible, and no content clips or overlaps.

If formula OCR, cross-page linkage, or graphic selection remains uncertain, report it as requiring manual confirmation. Never report it as passed based only on a successful API response.
