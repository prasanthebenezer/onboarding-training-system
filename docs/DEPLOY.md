# Deployment

## Current setup: Hostinger VPS srv1441644, behind the portfolio nginx
The portfolio nginx (Docker, repo `prasanthebenezer.github.io`) already owns ports 80/443, so this
app's Caddy is switched off and nginx proxies `training.prasanthebenezer.com` to the app.

| Item | Where |
|---|---|
| Repo on the VPS | `/root/onboarding-training-system` |
| Override (Caddy off, joins `prasanthebenezergithubio_default` as `training`) | `docker-compose.override.yml` (untracked). Template: `deploy/docker-compose.override.vps.yml` |
| TLS + proxy | `nginx.conf` in `prasanthebenezer.github.io` (certbot webroot cert, 500 MB upload limit). Reference copy: `deploy/nginx-training.conf` |
| DNS | GoDaddy: A record `training` → VPS IPv4 |
| Backups | nightly `vps-backup` at 02:30 UTC: `pg_dump` of the database, the media volume, `.env` and the override |

### Update to a new version
```bash
cd /root/onboarding-training-system && git pull && docker compose up -d --build
```

### Rebuild from scratch (new VPS or disaster recovery)
```bash
git clone https://github.com/prasanthebenezer/onboarding-training-system.git /root/onboarding-training-system
cd /root/onboarding-training-system
cp deploy/docker-compose.override.vps.yml docker-compose.override.yml
cp .env.example .env && nano .env    # or restore .env from the vps-backup
docker compose up -d --build         # the portfolio nginx stack must already be running
```
Then restore the database and media from the latest `vps-backup`, and make sure the portfolio
`nginx.conf` holds the server blocks from `deploy/nginx-training.conf`.

### Change an admin password
Run on the VPS. It asks for the password without showing it, updates `ADMIN_USERS` in `.env` and restarts the app:
```bash
./scripts/set-admin-password.sh             # first admin in ADMIN_USERS
./scripts/set-admin-password.sh supervisor1 # change or add another login
```
Passwords must be 10+ characters with no spaces and none of `: ; $ # \ ' " `` ` ``. Compose would alter
`$` and ` #` inside `.env`, and `:`/`;` separate the entries.

### Health check / uptime monitor
`GET https://training.prasanthebenezer.com/healthz` returns `{"ok":true}`. Use GET: HEAD returns 405.

## Alternative: standalone server (nothing else on ports 80/443)
Without an override file, `docker compose up -d --build` also starts Caddy, which gets the HTTPS certificate
itself once DNS points at the server. Then schedule `scripts/backup.sh` (database + media into `./backups`)
and copy `backups/` off the server:
```bash
15 2 * * * cd /path/to/onboarding-training-system && ./scripts/backup.sh >> backup.log 2>&1
```

## First use
`/admin` → Modules → **Import content from repository** → upload videos → Trainees → Assign.
