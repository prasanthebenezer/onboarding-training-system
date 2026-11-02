# Onboarding & Training System

Maintenance onboarding and training for technicians and engineers:

1. **Short videos (< 3 min)** in English, Arabic, Hindi or Malayalam. The trainee picks the language.
2. **Quiz** after the video (random questions from a bank, pass mark, limited attempts).
3. **Acknowledgment** (tick box + typed name), **PDF certificate**, and **supervisor sign-off**.
4. **Sharing over personal WhatsApp:** pick modules + trainees, then tap “Send on WhatsApp” to open a message with each person's personal link.
5. **Records for ISO 9001 / ISO 22000 audits** (clause 7.2 competence evidence): CSV export, hash-chained audit log.

Trial deployment: Hostinger VPS at `https://training.prasanthebenezer.com`.

## Quick start (local)
```bash
pip install -r requirements-dev.txt
ADMIN_USERS="admin:admin:Your Name" uvicorn app.main:app --reload
# open http://localhost:8000/admin → Courses & lessons → "+ New lesson"
pytest -q
```

## How it works
| Step | Who | Where |
|---|---|---|
| Draft script + quiz from SOP/manual | Claude + SME review | `content/modules/<slug>/` (script), quiz typed into the lesson editor |
| Build video visuals | Claude Motion artifact | see `docs/VIDEO_PIPELINE.md` |
| Record voiceover per language | Admin (Voice Studio) | merged with ffmpeg |
| Create/revise courses and lessons, upload MP4s | Admin | `/admin/modules` |
| Add trainees (form or CSV) | Admin | `/admin/trainees` |
| Assign + send links | Admin | `/admin/assign` → `/admin/assignments` |
| Watch → quiz → acknowledge | Trainee (phone) | personal link `/t/<token>` |
| Sign off, export, verify audit | Supervisor | `/admin/records`, `/admin/audit` |

## Docs
- `docs/DESIGN.md`: architecture, data model, record-keeping rules
- `docs/VIDEO_PIPELINE.md`: SOP → script → Motion → voiceover → MP4
- `docs/DEPLOY.md`: Hostinger VPS deployment, backups

## Adding or changing courses and lessons
Everything is done in the admin pages under **Courses & lessons**; the database holds the content.
- **+ New lesson:** title, summary, source document, pass mark, questions per attempt, attempts, acknowledgment
  text and the question bank (English required; Arabic, Hindi, Malayalam optional per question).
- **+ New course:** title, list order, and its lessons in order. **Edit course** renames, reorders, adds or removes lessons.
- **Revise** (on a lesson): publishes the next version (v1 → v2). Published versions never change, so trainees'
  records keep pointing at the version they took. Links already sent keep their version; new assignments get the
  new one. Tick *Copy the current videos* if only the text or quiz changed.
- Every publish and course change is written to the audit log.

## Content in this repo
The YAML files under `content/` are the original sources of the Plant Technology course. They were imported
once and are no longer read by the app (the tests still use them as sample data); edit content in the admin pages.

Course **Plant Technology** (`content/courses/plant-technology/`), from the Plant Technology Training Manual (SMP-MAINT-TRAIN-002 v1), in 4 lessons:

| Lesson | Manual section | Narration (EN) | Quiz bank |
|---|---|---|---|
| pt-01 Raw Material Composition | 1-2 | 262 words | 9 |
| pt-02 Pre- vs Post-Grinding | 3 | 213 words | 8 |
| pt-03 Six Main Processes | 4 | 243 words | 10 |
| pt-04 Secondary Services & Safety | 5 | 196 words | 9 |

Scripts and questions are **drafts** and need review by a subject-matter expert before release.
