# API reference

All JSON endpoints use `/api`. Choose a workspace with `X-Workspace: study` or `X-Workspace: practice`; the default is `study`. Downloads also accept `?workspace=study`. This is a loopback-only single-user app, not an authenticated public service.

| Method | Route | Behavior |
|---|---|---|
| GET | `/api/health` | Service readiness |
| GET | `/api/state` | Current phase, counts, delay, AI configuration (no key) |
| GET | `/api/guidelines` | Labels, R1–R8 and score rubric |
| GET | `/api/clips` | Current workspace queue; no prior labels |
| POST | `/api/clips` | Multipart upload; dataset must be unlocked |
| GET | `/media/{id}` | Local playback, supporting HTTP Range |
| POST | `/api/annotate` | Append one annotation and its segments |
| GET | `/api/annotations/{id}?pass=1` | Saved annotation; pass 1 is sealed while blind |
| POST | `/api/lock-pass1` | Freeze complete first pass and dataset |
| POST | `/api/start-pass2` | Enforce delay, then enable blind submissions |
| GET | `/api/agreement` | Complete-pass agreement, kappa and disagreements |
| GET | `/api/captions/{id}` | Caption and any committed scores |
| POST | `/api/caption/{id}` | Immutable manual import or Gemini generation |
| POST | `/api/scores/{id}` | Commit human scores once |
| POST | `/api/judge/{id}` | Independently judge actual media; human scores required first |
| GET | `/api/comparison` | Human/judge comparisons with explicit denominators |
| GET / POST | `/api/revisions` | Read/record rule revisions after both passes |
| GET | `/api/export` | ZIP with CSVs, JSON, results and guideline history |
| GET | `/api/export?format=json` | JSON-only equivalent |

Annotation payload:

```json
{
  "clip_id": "an-existing-clip-id",
  "pass": 1,
  "label": "Safe",
  "rule_id": "R6",
  "rationale": "A sequence of tones is audible; no speech or harmful event is present.",
  "flagged": false,
  "flag_ts": null,
  "segments": [{"start_s": 0.0, "end_s": 0.5, "label": "Safe"}]
}
```

Human score payload:

```json
{
  "accuracy": 5,
  "omission": 4,
  "hallucination": 5,
  "rationale": "The caption correctly describes the tones but omits the silence between them.",
  "corrected_caption": "Several brief tones repeat with pauses of silence."
}
```

These are illustrative requests, not stored study results. Caption generation uses `{"mode":"gemini","consent":true}`; manual import uses `{"mode":"manual","caption_text":"...","model":"actual source"}`. Judge requests use `{"consent":true}`. Mutations without fields use `{}`.

Errors are JSON `{"error":"message"}`: 400 invalid fields, 403 host/origin rejection, 404 missing or wrong-workspace record, 409 immutable/duplicate/conflicting operation, 413 oversized media, 423 sealed/waiting study, 502 provider failure, 503 missing provider configuration. There is no public rate-limited API or multi-user identity layer. Do not publish this local service directly.
