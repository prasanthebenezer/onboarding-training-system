#!/usr/bin/env bash
# Change (or add) an admin/supervisor login in .env, then restart the app.
# Run it yourself on the VPS so the password is never shown or logged:
#   ./scripts/set-admin-password.sh             # changes the first admin (prasanth)
#   ./scripts/set-admin-password.sh <username>  # changes or adds that admin
# Logins are stored in ADMIN_USERS as  username:password:Display Name;...
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo ".env not found in $PWD" >&2; exit 1; }

current=$(grep -m1 '^ADMIN_USERS=' .env | cut -d= -f2- || true)
user=${1:-$(printf '%s' "$current" | cut -d: -f1)}
[[ -n $user ]] || { echo "No admin user found; pass a username." >&2; exit 1; }
[[ $user =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Username may only use letters, digits, . _ -" >&2; exit 1; }

read -rsp "New password for '$user': " pw1; echo
read -rsp "Repeat password: " pw2; echo
[[ $pw1 == "$pw2" ]] || { echo "Passwords do not match." >&2; exit 1; }
(( ${#pw1} >= 10 )) || { echo "Use at least 10 characters." >&2; exit 1; }
# ':' and ';' separate ADMIN_USERS entries. Docker Compose also rewrites .env values:
# '$' starts a variable and ' #' starts a comment, so the app would get a different password.
if [[ $pw1 =~ [[:space:]] || $pw1 == *[:\;\$#\\\'\"\`]* ]]; then
  echo "The password cannot contain spaces or any of these: : ; \$ # \\ ' \" \`" >&2; exit 1
fi

NEWPW=$pw1 TARGET=$user CURRENT=$current python3 - <<'PY'
import os
pw, user, cur = os.environ["NEWPW"], os.environ["TARGET"], os.environ["CURRENT"]
entries, found = [], False
for e in filter(None, (x.strip() for x in cur.split(";"))):
    parts = e.split(":", 2)
    if parts[0] == user:
        name = parts[2] if len(parts) == 3 else user
        e, found = f"{user}:{pw}:{name}", True
    entries.append(e)
if not found:
    entries.append(f"{user}:{pw}:{user}")
lines = open(".env").read().splitlines()
new = "ADMIN_USERS=" + ";".join(entries)
lines = [new if l.startswith("ADMIN_USERS=") else l for l in lines]
if new not in lines:
    lines.append(new)
fd = os.open(".env.tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines) + "\n")
os.replace(".env.tmp", ".env")
PY

docker compose up -d app >/dev/null
echo "Password for '$user' updated; the app was restarted."
