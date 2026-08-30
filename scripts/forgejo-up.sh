#!/usr/bin/env bash
# Bring up the local Forgejo instance and print the next steps.
#
# Starts the Forgejo container, waits until the web UI responds, then tells you
# exactly what to do next (complete setup, push the repo, register a runner).
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

COMPOSE="docker compose -f docker-compose.forgejo.yml"
URL="http://localhost:3000"

echo "Starting Forgejo..."
$COMPOSE up -d forgejo >/dev/null

echo -n "Waiting for Forgejo to respond at $URL "
for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$URL/" 2>/dev/null || echo 000)"
    if [ "$code" = "200" ]; then
        echo " up."
        break
    fi
    echo -n "."
    sleep 1
done
if [ "${code:-000}" != "200" ]; then
    echo
    echo "Forgejo did not come up. Check: $COMPOSE logs forgejo" >&2
    exit 1
fi

# Has first-run setup completed? The API version endpoint only works afterwards.
setup_done=0
if curl -s "$URL/api/v1/version" 2>/dev/null | grep -q '"version"'; then
    setup_done=1
fi

echo
echo "Forgejo is running at $URL"
echo

if [ "$setup_done" -eq 0 ]; then
    cat <<EOF
Next steps:
  1. Open $URL and complete the first-run install (SQLite is fine),
     then register your admin user.
  2. Create a repository named 'motorsport-events'.
  3. Add the remote and push:
       git remote add forgejo $URL/<you>/motorsport-events.git
       git push forgejo main
  4. Register a runner:  make forgejo-register TOKEN=<token>
     (token from: Settings -> Actions -> Runners -> Create new runner)
  5. Start the runner:   make forgejo-runner
EOF
else
    cat <<EOF
Setup already complete. If you haven't yet:
  - Add the remote:      git remote add forgejo $URL/<you>/motorsport-events.git
  - Push:                git push forgejo main
  - Register a runner:   make forgejo-register TOKEN=<token>
  - Start the runner:    make forgejo-runner
EOF
fi
