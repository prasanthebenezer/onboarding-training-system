# Deploy on the Hostinger VPS (trial)

Prerequisites: Docker + Docker Compose plugin on the VPS. A DNS **A record** for `training.prasanthebenezer.com` pointing to the VPS IP. Ports 80/443 open.

```bash
git clone https://github.com/prasanthebenezer/onboarding-training-system.git /opt/onboarding-training-system
cd /opt/onboarding-training-system
cp .env.example .env
nano .env        # set SECRET_KEY (e.g. `openssl rand -hex 32`), POSTGRES_PASSWORD (also in DATABASE_URL), ADMIN_USERS
docker compose up -d --build
docker compose logs -f app
```
Caddy gets the HTTPS certificate automatically once DNS resolves.

First use: `https://training.prasanthebenezer.com/admin` → Modules → **Import content from repository** → upload videos → Trainees → Assign.

Update to a new version: `git pull && docker compose up -d --build`.

## Backups (do not skip: these are audit records)
```bash
crontab -e
15 2 * * * cd /opt/onboarding-training-system && ./scripts/backup.sh >> backup.log 2>&1
```
Copy `backups/` off the VPS regularly (e.g. `rclone` to cloud storage) and test a restore once.
