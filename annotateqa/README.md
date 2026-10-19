# AnnotateQA

A local video/audio annotation workbench and AI-caption quality study, built for Aayansh Singh’s annotation portfolio. React + TypeScript + Vite + Tailwind, Flask, SQLite, scikit-learn, and optional Gemini via `google-genai`.

The project demonstrates the actual tasks in the supplied Micro1 description: evidence-based labeling, guideline compliance, timestamped review flags, written feedback, AI-output evaluation, quality assurance and process improvement. It is a tool for collecting evidence of those skills; building it does not establish annotation experience or guarantee selection.

## Start

**On the prepared workspace:** run `python start.py`, or double-click `START_WINDOWS.bat`. Open **http://127.0.0.1:5000**.

**On a fresh computer:** install Python 3.11+ and Node.js 22+, then run:

```sh
python start.py --setup
```

This creates a project virtual environment, installs dependencies, builds the frontend, copies `.env.example` to `.env` when needed, seeds four original practice clips, and starts Flask on loopback. Internet is required for first-time dependency installation. It never overwrites an existing `.env` or your annotations.

For subsequent starts:

```sh
python start.py
```

Stop with Ctrl+C. Your records remain in `data/annotateqa.sqlite3`. The app prefers Waitress; if it is not installed, it uses Flask’s local development server. This fallback is for local use only.

## What works

- Upload video/audio with title, source page, licence, attribution, duration and content hash. Duplicate media in a workspace is rejected.
- HTML5 media playback and seeking. MP4, WebM, OGV, WAV, MP3, OGG and M4A containers are accepted; actual playback depends on your browser’s codec support.
- Five moderation labels and eight always-visible guideline rules. A rule and evidence rationale are mandatory.
- Multiple timestamped event segments, plus a review flag at a precise playback time.
- Append-only annotations and segments enforced both through the API and SQLite triggers. A submitted annotation cannot be edited or resubmitted.
- Pass-1 locking, a snapshotted waiting period, shuffled pass-2 queue, and server-side sealing of pass-1 records, reports and exports until pass 2 is complete.
- Manual caption import or real Gemini media caption generation. Captions become immutable once saved.
- Human accuracy, completeness/omission and grounding/hallucination scores, written feedback and corrected descriptions.
- An independent Gemini judge that receives the media, caption and rubric, **never your human scores or feedback**. Your scores must be submitted first.
- Clip-label agreement, Cohen’s kappa, a confusion matrix, disagreement rationales and human–judge comparison.
- Evidence-linked guideline revisions; export generates v2 and a changelog while retaining v1 for both original passes.
- ZIP/CSV/JSON exports that contain real database records and never contain media bytes or credentials.

## Two separate workspaces

**Practice workspace:** four original synthetic clips (two silent videos and two tone-based audio recordings), released with CC0 dedication. No labels, captions, human scores or judge results are prefilled. The wait is zero minutes. It is an interaction exercise, not a representative moderation benchmark. Study and practice exports are explicitly named.

**My annotation study:** starts empty. Add the real licensed data you will evaluate. The default separation period is 60 minutes. Practice annotations never contribute to this workspace’s metrics.

## Run the actual study

1. Switch to **My annotation study**. Add 20 video and 10 audio clips, or use the optional Wikimedia collector below. The target is a study plan, not a hard-coded or claimed completion count.
2. Read `guideline_v1.md`, including the label priority rule. Play each clip. Submit its label, rule and rationale. Add event segments when useful. Flag unclear or unplayable media with R8.
3. Review your dataset before locking: no new clips can be added after the lock. Click **Lock pass 1** after all clips are annotated.
4. During the wait, generate or import captions and score 12 yourself. All dimensions use **1 = worst, 5 = best**. Completeness 5 means no important omissions; grounding 5 means no unsupported details.
5. Start pass 2 when the timer reaches zero. Annotate the shuffled queue independently under **the same v1 guideline**. Do not consult prior downloads, screenshots or your SQLite file.
6. Open **Agreement report** when every second-pass annotation is submitted. Inspect disagreements and flagged cases. Run the judge from Caption QA after your scores are sealed.
7. In **Guidelines**, link each proposed rewrite to actual disagreeing clips. Record the ambiguity and the clearer rule.
8. Export the evidence bundle. Use its actual values when describing your work. Choose and explain your three hardest clips yourself; the exported report only suggests disagreement/flag candidates.

The same person performs both passes, so this is **intra-rater consistency**, not independent inter-annotator accuracy. A one-hour gap reduces immediate recall but does not eliminate it. Local database ownership also means the tool cannot prevent its owner from inspecting the database outside the app; sealing is enforced across the application’s API, not against a computer administrator.

## Real licensed dataset collection

The repository includes a collector using Wikimedia Commons’ public API. It searches varied topics, filters reported CC BY/CC BY-SA, CC0 or public-domain licences, selects clips lasting 2–60 seconds, records author/source information, prefers browser-compatible derivatives, caps each download at 25 MB, and writes only real successful downloads. Reruns preserve existing clips and stop at the requested total.

With the project environment active, run:

```sh
python scripts/collect_commons.py --videos 20 --audio 10
```

On Windows without activation, use `.venv\Scripts\python.exe scripts\collect_commons.py`. The source manifest is written to `data/source_manifest.json`. Check every source page and attribution, then play each clip before starting. A repository’s reported licence is provenance, not a guarantee of all permissions. Pexels/Pixabay terms are not automatically Creative Commons; record the actual applicable licence if importing from elsewhere.

This environment blocked external downloads, so **30 public clips have not been collected or claimed here**. The collector is implemented but its live Wikimedia path was not exercised. The original practice clips are bundled and work without downloading media. If Commons returns fewer qualifying clips, the collector reports the actual count; add the remainder through the upload dialog. Nature and sound samples alone will produce a Safe-heavy dataset, so curate diverse permitted material before making moderation-quality claims.

## Gemini configuration

Edit the gitignored `.env`:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
PASS2_DELAY_MINUTES=60
PORT=5000
```

Use a video/audio-capable model available to your account. The model is configurable because access and model availability change. Restart after changing `.env`. The backend uploads the actual clip through the Gemini Files API, waits for processing, generates a caption or structured JSON evaluation, and attempts to delete the temporary provider file in `finally`. A failed provider cleanup may leave the file subject to the provider’s retention policy. No API key reaches the browser.

Each AI action requires a checkbox permitting that clip to be sent to Gemini. Without a key, uploads, annotations, blind passes, manual caption reviews, metrics and exports still work. The app never fabricates an AI response or silently replaces a failed call with a mock. Live Gemini generation/judging has not been verified here because no key was provided; unit tests use a clearly isolated fake provider to validate request boundaries and score handling.

References: [Gemini video API](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding), [Google Gen AI Python SDK](https://github.com/googleapis/python-genai), [Wikimedia media API](https://www.mediawiki.org/wiki/Extension:TimedMediaHandler/API).

## What the metrics mean

**Observed agreement** = identical paired clip labels / paired clips × 100.

**Cohen’s kappa** = `(p_observed - p_chance) / (1 - p_chance)`, computed with scikit-learn over the same ordered five-label vocabulary. If every clip has the same label in both passes, chance agreement is 1 and kappa is undefined; the UI displays a dash and explanation instead of inventing zero or one.

**Confusion matrix**: rows = pass-1 labels, columns = pass-2 labels. The diagonal contains matching labels. These metrics do not measure segment-boundary agreement and do not prove that labels are correct.

**Judge within one point**: for each caption with both scorers, compare all three dimensions. Count `abs(human - judge) <= 1` and divide by `3 × paired_caption_count`. Dimension-specific percentages use their own paired-caption denominator. Missing judge results are excluded, not treated as zero. A Gemini judge is not ground truth and may share biases with the model that generated the caption.

## Results and guideline changes

No real study has been performed as part of the build. Accordingly, no agreement, kappa, caption-evaluation count or improvement percentage is claimed in this README.

The **Export** button generates:

| File | Contents |
|---|---|
| `labels.csv` | Both passes, rule, rationale, flag, guideline version, timestamps |
| `segments.csv` | Clip/pass/start/end/label for timestamped events |
| `clips.csv` | Source, licence, attribution, duration and media hash |
| `captions.csv` | Fixed caption, model and provenance |
| `caption_scores.csv` | Human/judge scores, rationales, corrections and model |
| `study.json` | Full machine-readable records and calculated results |
| `RESULTS.md` | Actual results, matrix, methodology and reflection candidates |
| `guideline_v1.md` | The immutable guide used for the two passes |
| `guideline_v2.md` | Original rules plus your evidence-linked rewrites |
| `CHANGELOG.md` | Exact ambiguity, changed rule and linked disagreeing clip IDs |

Exports are blocked from pass-1 locking until pass 2 finishes. Before locking, an export may contain partial pass-1 work and explicitly has no agreement result. CSV fields beginning with spreadsheet formula characters are escaped; `study.json` preserves their original text.

The root-level CSVs contain headers only. They are templates, not exported results. Root `guideline_v2.md` and `CHANGELOG.md` are honest initial placeholders; download the evidence bundle for actual study-generated versions.

## Development and checks

```sh
# Backend; default loopback port 5000
python -m backend.app

# Frontend development; API proxy points at port 5000
npm run dev

# Type-check and production build
npm run build

# Backend behavioral tests; no network or Gemini key required
python -m unittest discover -s tests -v

# React interaction tests in an isolated DOM (not a real browser)
npm run test:ui
```

The 11 behavioral tests cover blank results, source tracking, media range responses, validation, timestamp bounds, duplicate submissions, database append-only triggers, blind-pass sealing, snapshotted delays, workspace isolation, independent scoring, evidence-linked revisions, exports and known metric cases. Tests use disposable databases under `tests/.scratch` and do not write to your study.

Five React interaction tests also passed in jsdom: required annotation fields and segments, locked waiting state, sealed agreement access, human-first caption scoring, and missing-key/manual-caption behavior. See `docs/VALIDATION.md` for the exact verification scope.

Browser automation could not connect in the build environment. Visual/browser interaction verification is therefore not claimed. Backend tests and the frontend production build are separate checks; neither establishes live Gemini correctness or a completed annotation study.

## Data handling and scope

- Single-user, local-first app. Loopback binding, host validation and same-origin write checks are deliberate. It has no multi-user authentication; do not expose it to a public network.
- Only use public licensed media or your own authorized material. Keep confidential data out. Do not identify faces or infer sensitive personal attributes.
- Media is stored locally for playback. A flag itself stores only its timestamp, label and written rationale; there is no extra flagged-media copy. Exported evidence excludes all raw media.
- Raw media, `.env`, SQLite files and generated results are gitignored. Rationales may contain sensitive information: review exports before sharing.
- The study dataset is frozen when pass 1 locks. No reset/delete UI is included, because silently discarding evidence would undermine the audit trail. For another independent study, use a new project copy with a fresh `data` directory after backing up the old one.
- These moderation rules are a portfolio exercise drafted in the supplied brief, not Micro1’s internal moderation policy.

## Project layout

```text
backend/             Flask routes, SQLite schema, Gemini integration and rules
src/                 React screens, shared UI and responsive styling
scripts/             Original practice-media generator and Commons collector
demo/                Bundled original CC0 practice media
tests/               Data-integrity and workflow regression tests
agreement.py         scikit-learn metrics
start.py             Cross-platform setup/start launcher
guideline_v1.md      Rules used for both passes
dist/                Built frontend in the downloadable project bundle
data/                Local runtime data (created on first run; gitignored)
```

When extending the app, keep both passes on a fixed guideline version, preserve the API sealing checks, add tests for new export/read paths, and never seed user-facing metrics with synthetic study results.
