# Design

## Architecture
```
Admin (browser) ──HTTP Basic──► FastAPI app ──► PostgreSQL (records, audit log)
                                   │  └──────► /data/media (MP4 per module version × language)
Trainee phone ◄── WhatsApp (admin taps wa.me link, presses Send)
      └── personal link /t/<token> ──► confirm Employee ID ──► watch ──► quiz ──► acknowledge ──► PDF
Caddy (HTTPS, Let's Encrypt) in front. All three run in Docker Compose on the VPS.
```

## Key decisions
| Topic | Decision | Why |
|---|---|---|
| WhatsApp | `wa.me` click-to-chat from the admin's personal WhatsApp | No Business API. Automating a personal account (whatsapp-web.js, Baileys) breaks WhatsApp's terms and risks a ban. |
| Trainee identity | Unguessable per-person link (`token_urlsafe(24)`) + Employee ID check, 5 tries max | There's no OTP channel without the Business API. Recorded IP and user agent add supporting evidence. |
| Courses | A course (e.g. Plant Technology, later Safety, machines) lists its lessons in order; courses are created and edited in Admin → Courses & lessons (every change audit-logged). Assign a whole course or single lessons. Within one link, a course's lessons unlock in order. Each lesson keeps its own record and certificate; when every lesson (current version) of a course is passed and acknowledged, an insert-only CourseCompletion with its own certificate (CRS-…) lists the lesson certificates. In code a lesson is still called a `Module`. | Structured learning; one certificate per course for the training file |
| Video language | Chosen by the trainee after the Employee ID check (once per visit, remembered for the next), changeable on every page; falls back to English with a notice when a module has no video in that language yet. Each change is audit-logged. Admins don't set it. | Trainees know their own language best |
| Watch requirement | None (80% rule dropped). Play/ended events are logged as evidence. The quiz unlocks once the video page is opened. | Your decision |
| Quiz | Random N from bank, fixed per attempt (refresh does not re-roll), pass mark %, max attempts. Answers stored. | Assessment evidence |
| Content control | Lessons are created and revised in the admin lesson editor. A published version is **frozen**: revising publishes the next version (a revision with no changes is rejected), and each publish is audit-logged with its content hash | ISO document control; old records keep pointing at the version actually taken |
| Videos | One MP4 per module version per language; SHA-256 stored | Proves which file was shown |
| Records | Attempts and acknowledgments are insert-only; every action is in a **hash-chained audit log** (`/admin/audit` verifies) | Tamper-evidence. Off-server backups still required. |
| Supervisor sign-off | Logged-in admin's display name + time, mirroring section 7 of the manual | The manual requires a supervisor signature |
| Admin auth | HTTP Basic over HTTPS, users from `ADMIN_USERS` env | Fine for a trial. Move to SSO/proper accounts before org-wide rollout. |

## Data model
`Trainee` → `Assignment` (one link, one due date) → `AssignmentItem` (one per module version; status pending/watched/passed/failed)
→ `ViewEvent`*, `QuizAttempt`*, `Acknowledgment` (certificate no., typed name, supervisor sign-off).
`Course` → `CourseLesson` (ordered) → `Module` (= lesson) → `ModuleVersion` (frozen snapshot of quiz + acknowledgment text) → `Video` (per language).
`CourseCompletion`: insert-only, snapshot of the lesson evidence.
`AuditLog`: append-only, `hash = sha256(prev_hash + entry)`.

## ISO 9001 / 22000 evidence produced per completion
Who (name, employee ID, role) · What (module, version, source document, video language and file hash) ·
When (opened, played, quiz started/submitted, acknowledged, signed off) · Result (score, pass mark, attempt no., answers) ·
Acknowledgment statement + typed name · Supervisor sign-off · Certificate PDF · CSV export.

## Known limits (trial)
- Trainee-facing UI text is English; video and quiz can be in any of the 4 languages (quiz falls back to English where no translation exists).
- The PDF uses Latin-only fonts; trainee names must be entered in Latin script.
- Admin accounts come from the env file; no password reset UI.
- No automatic reminders (personal WhatsApp). The dashboard shows overdue items so you can resend.
