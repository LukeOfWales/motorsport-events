# Local Forgejo Actions (CI) setup

This project uses a two-stage CI flow:

1. Pre-GitHub (local): a git **pre-push hook** runs the test suite before any
   push, and a local **Forgejo** instance runs the workflow as a CI dashboard
   you can iterate on before it reaches GitHub.
2. GitHub (authoritative): `.github/workflows/tests.yml` runs on GitHub Actions
   after you push to `origin`.

The workflow at `.forgejo/workflows/tests.yml` mirrors the GitHub one, so the
same checks run at both stages.

## Recommended flow

```
edit code
  -> git push forgejo main     # pre-push hook runs tests; Forgejo Actions runs
  -> (green in Forgejo)
  -> git push origin  main     # pre-push hook runs tests; GitHub Actions runs
```

The pre-push hook is the actual gate that stops broken code leaving the machine;
Forgejo Actions gives you a CI dashboard/history and a place to develop workflow
changes before they hit GitHub.

## Pre-push hook

Install it once after cloning (hooks aren't version-controlled):

```bash
./scripts/install-hooks.sh
```

Every `git push` then runs `pytest` first and aborts the push on failure.
Bypass in an emergency with `MSE_SKIP_HOOK=1 git push`.

## Local Forgejo instance

Run a Forgejo instance and a runner locally to develop and execute these
workflows offline. Requires Docker. The `make` targets wrap the Docker Compose
commands.

### 1. Start Forgejo

```bash
make forgejo-up
```

This starts Forgejo, waits until it responds, and prints the next steps. Open
http://localhost:3000 and complete the first-run install (SQLite is fine), then
register your admin user.

### 2. Push this repo to your local Forgejo

Create a repository in the Forgejo UI (e.g. `motorsport-events`), then add it as
a second remote alongside GitHub (`origin`) and push:

```bash
git remote add forgejo http://localhost:3000/<you>/motorsport-events.git
git push forgejo main
```

### 3. Register and start a runner

Get a registration token from the UI (`Settings -> Actions -> Runners -> Create
new runner`, or site-wide under Site Administration), then:

```bash
make forgejo-register TOKEN=<token>   # one-off registration
make forgejo-runner                   # start the runner daemon
```

### 4. Trigger a run

Push a commit (or open a PR) to `main` on the Forgejo remote. The workflow
appears under the repo's **Actions** tab and runs the test suite in a
`catthehacker/ubuntu:act-latest` container (Python + git + node + pip, matching
the `ubuntu-latest` label the runner is registered with).

### Other targets

```bash
make forgejo-status   # container status
make forgejo-logs     # tail Forgejo + runner logs
make forgejo-down     # stop everything
```

## Notes

- Data persists in `./.forgejo-data` (Forgejo) and `./.forgejo-runner` (runner
  config); both are git-ignored.
- The workflow file is portable: the same steps run on GitHub Actions
  (`.github/workflows/tests.yml`) and Forgejo (`.forgejo/workflows/tests.yml`).
  Keeping both lets the project build on either forge.
