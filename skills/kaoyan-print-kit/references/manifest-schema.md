# Manifest Schema

Use UTF-8 JSON. All paths may be absolute or relative to the manifest.

```json
{
  "mode": "memorization",
  "title": "极限核心公式",
  "subject": "高等数学",
  "chapter": "函数、极限与连续",
  "print_profile": "bw",
  "source_label": "高等数学讲义.pdf",
  "sections": [
    {
      "title": "常用极限",
      "blocks": [
        {
          "type": "formula",
          "formula": "lim(x->0) sin(x)/x = 1",
          "notes": "条件：x 以弧度计。"
        }
      ]
    }
  ]
}
```

Required top-level fields: `mode`, `title`, `subject`, `chapter`, `print_profile`, and `sections`.

Optional `include_toc: true` adds a PDF table of contents with resolved page numbers and a refreshable DOCX TOC field. Give each section a stable optional `id` when using a directory.

Optional `density` accepts `compact`, `standard`, or `spacious` and changes typography and paragraph rhythm without changing content.

Allowed modes: `memorization`, `mistakes`, `diagnostic`.

Allowed print profiles: `bw`, `color`.

Supported blocks:

- `paragraph`: `text`
- `bullets`: `items`
- `callout`: `label`, `text`
- `formula`: `formula`, optional `notes`, optional `source`
- `definition`: `term`, `definition`, optional `keywords`, `boundary`, `counterexample`, `source`
- `image`: `path`, optional `caption`, `source`
- `question`: `id`, `number`, `stem`, optional `image`, `answer_space_lines`, `answer`, `analysis`, `error_cause`, `knowledge_points`, `source`
- `diagnostic`: `id`, `level`, `prompt`, `answer_space_lines`, `answer`, `rubric`, `misconceptions`, `source`
- `knowledge_point`: `id`, `title`, `importance` (`A`, `B`, or `C`), `personal_weak`, `grading_evidence`, and provenance-labeled `segments`
- `comparison`: `title`, visible `origin_label`, optional `source`, `headers`, and equal-width `rows`
- `process` or `timeline`: `title`, visible `origin_label`, optional `source`, and ordered `items`
- `relationship`: `title`, visible `origin_label`, optional `source`, and `relations` containing `from`, `relation`, and `to`
- `recall`: optional `label` and `lines`

The generator hides answer-bearing fields in `practice` output. It shows them in `answers` output.

Raster image blocks are sized from their pixel dimensions at a target of 150 DPI and are reduced further to fit the page. The generator does not stretch low-resolution images to the full content width.

