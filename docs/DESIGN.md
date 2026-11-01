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
| Watch requirement | None (80% rule dropped). Play/ended events are logged as evidence. The quiz unlocks once the video page is opened. | Your decision |
| Quiz | Random N from bank, fixed per attempt (refresh does not re-roll), pass mark %, max attempts. Answers stored. | Assessment evidence |
| Content control | YAML in git; a published version is **frozen**: changed content without a version bump is rejected | ISO document control; old records keep pointing at the version actually taken |
| Videos | One MP4 per module version per language; SHA-256 stored | Proves which file was shown |
| Records | Attempts and acknowledgments are insert-only; every action is in a **hash-chained audit log** (`/admin/audit` verifies) | Tamper-evidence. Off-server backups still required. |
| Supervisor sign-off | Logged-in admin's display name + time, mirroring section 7 of the manual | The manual requires a supervisor signature |
| Admin auth | HTTP Basic over HTTPS, users from `ADMIN_USERS` env | Fine for a trial. Move to SSO/proper accounts before org-wide rollout. |

## Data model
`Trainee` → `Assignment` (one link, one due date) → `AssignmentItem` (one per module version; status pending/watched/passed/failed)
→ `ViewEvent`*, `QuizAttempt`*, `Acknowledgment` (certificate no., typed name, supervisor sign-off).
`Module` → `ModuleVersion` (frozen snapshot of quiz + acknowledgment text) → `Video` (per language).
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
