#!/usr/bin/env bash
# Install the project's git hooks into .git/hooks (which isn't version-controlled).
# Run once after cloning:  ./scripts/install-hooks.sh
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

install -m 0755 scripts/pre-push .git/hooks/pre-push
echo "Installed .git/hooks/pre-push"
echo "Pushes now run the test suite first (bypass with MSE_SKIP_HOOK=1)."
