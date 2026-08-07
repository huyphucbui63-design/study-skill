# Data Contract

## Paths

All paths are relative to the repository unless the user chooses another data directory.

- `data/kaoyan-journey.md`: user-owned, append-only journey notes.
- `data/study-records.jsonl`: formal study records retained by explicit authorization.
- `data/strategy-history.jsonl`: append-only strategy analyses and decision events.

The entire `data/` directory is ignored by Git. Commit only templates, schemas, tests, and synthetic examples.

## Journey

The user may maintain the Markdown file directly. Machine-added entries use delimited sections so parsing does not depend on prose wording. Every machine-added field has `input_origin: user`. Append a later correction; never edit an older entry in place.

Required entry fields are date, target, stage, subject progress, study state, main problems, constraints, ideas, and important decisions. Preserve strings exactly. Empty lists or strings are allowed when the user has no information.

## Study Record Filtering

Long-term strategy may use a study record only when all are true:

1. It is a JSON object in `study-records.jsonl`.
2. It is a formal record rather than a session draft.
3. `save_authorization.confirmed` is `true`.
4. `save_authorization.choice` is `keep_full` or `keep_summary`.
5. `save_authorization.authorized_at` is present.

For `keep_summary`, expose only the user summary and non-sensitive summary fields. Do not expose image references, detailed observations, or raw recognition payloads. Correction events remain separate and traceable; do not replace earlier lines.

## Strategy History

Append one JSON object per line. Supported event types are `strategy_analysis`, `strategy_state_analysis`, and `strategy_decision`. The saver generates IDs and timestamps; callers cannot backdate them.

`strategy_analysis` stores proposed recommendations. The user's retention choice immediately appends one decision event per recommendation as `accepted` or `undecided`. Later `decide` operations append new decision events; reduction by time yields current decision state. `strategy_state_analysis` omits recommendations entirely. `no_save` appends nothing.

Malformed JSONL is a blocking error with a line number. Never skip a bad line, silently normalize history, or overwrite the file.

## Authorization

Every writing command requires `--authorize-write`, which represents a clear choice in the current interaction. Read commands never create missing files. An authorization flag is operation-scoped; it is not permanent consent.
