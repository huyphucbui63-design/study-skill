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

The generator hides answer-bearing fields in `practice` output. It shows them in `answers` output.

