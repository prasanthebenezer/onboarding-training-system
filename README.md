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
# open http://localhost:8000/admin → Modules → "Import content from repository"
pytest -q
```

## How it works
| Step | Who | Where |
|---|---|---|
| Draft script + quiz from SOP/manual | Claude + SME review | `content/modules/<slug>/` |
| Build video visuals | Claude Motion artifact | see `docs/VIDEO_PIPELINE.md` |
| Record voiceover per language | Admin (Voice Studio) | merged with ffmpeg |
| Import content, upload MP4s | Admin | `/admin/modules` |
| Add trainees (form or CSV) | Admin | `/admin/trainees` |
| Assign + send links | Admin | `/admin/assign` → `/admin/assignments` |
| Watch → quiz → acknowledge | Trainee (phone) | personal link `/t/<token>` |
| Sign off, export, verify audit | Supervisor | `/admin/records`, `/admin/audit` |

## Docs
- `docs/DESIGN.md`: architecture, data model, record-keeping rules
- `docs/VIDEO_PIPELINE.md`: SOP → script → Motion → voiceover → MP4
- `docs/DEPLOY.md`: Hostinger VPS deployment, backups

## Adding a course (e.g. Safety)
1. Add each lesson as `content/modules/<lesson-slug>/module.yaml` (quiz, acknowledgment) and `script.en.md`.
2. Add `content/courses/<course-slug>/course.yaml`:
   ```yaml
   slug: safety
   title: "Safety"
   summary: "..."
   position: 20          # courses are listed in this order
   lessons:              # lesson order
     - safety-01-loto
     - safety-02-confined-space
   ```
3. Commit and push, `git pull` on the VPS, then Admin → **Courses & lessons** → **Import content from repository**.

## Content in this repo
Course **Plant Technology** (`content/courses/plant-technology/`), from the Plant Technology Training Manual (SMP-MAINT-TRAIN-002 v1), in 4 lessons:

| Lesson | Manual section | Narration (EN) | Quiz bank |
|---|---|---|---|
| pt-01 Raw Material Composition | 1-2 | 262 words | 9 |
| pt-02 Pre- vs Post-Grinding | 3 | 213 words | 8 |
| pt-03 Six Main Processes | 4 | 243 words | 10 |
| pt-04 Secondary Services & Safety | 5 | 196 words | 9 |

Scripts and questions are **drafts** and need review by a subject-matter expert before release.
