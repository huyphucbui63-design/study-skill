# Grading And Evidence

## Independent Markers

- `A`: core, frequently tested, prerequisite, or exact material with high exam cost if forgotten.
- `B`: important supporting content or common application.
- `C`: lower-frequency extension, detail, or recognition-level content.
- `R`: the user's personal weak point. R is independent of A/B/C; valid combinations include A+R, B+R, and C+R.

Do not infer R from importance. Set R from a user designation or an explicitly retained learning record. A model may suggest R only as an unconfirmed proposal.

## Allowed Evidence

Each marker has its own status and evidence list. Store A/B/C evidence in `importance_evidence` and R evidence in `weakness_evidence`; never use one shared list to imply both claims. Each claim must cite at least one evidence item with a statement, confidence, and reference where available.

1. `user_designation`: direct user choice.
2. `exam_requirement`: official syllabus or explicit exam requirement.
3. `source_emphasis`: headings, bold text, repeated emphasis, or source priority labels.
4. `historical_question`: reliable past-question evidence with year/question citation.
5. `retained_study_record`: a record the user explicitly authorized for long-term use.
6. `ai_inference`: model reasoning from the current sources; always an AI suggestion.

Never cite unretained session data as long-term evidence. Never convert a model inference into a user designation.

## Independent Review Status

- `importance_status` records confirmation of A/B/C only.
- `weakness_status` records confirmation of R only.
- `confirmed` means the user confirmed or directly supplied that marker.
- `ai_suggestion` means the model proposed that marker and the user has not confirmed it.

Final generation requires both statuses to be confirmed for every point. A confirmed `personal_weak: true` accepts only `user_designation` or `retained_study_record` evidence. If evidence is weak, keep that marker as a suggestion and request correction rather than manufacturing certainty.
