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

Below is how to run a Forgejo instance and a runner locally so you can develop
and execute these workflows offline. Requires Docker.

## 1. Start Forgejo

```bash
docker compose -f docker-compose.forgejo.yml up -d forgejo
```

Open http://localhost:3000 and complete the first-run install screen (SQLite is
fine for local use), then register your admin user.

## 2. Push this repo to your local Forgejo

Create a repository in the Forgejo UI (e.g. `motorsport-events`), then add it as
a second remote alongside GitHub (`origin`) and push:

```bash
git remote add forgejo http://localhost:3000/<you>/motorsport-events.git
git push forgejo main
```

You now have two remotes: `forgejo` (pre-GitHub CI) and `origin` (GitHub). Push
to `forgejo` first, and to `origin` once it's green.

## 3. Register a runner

Get a registration token from the UI:

- Repo-level: `Settings -> Actions -> Runners -> Create new runner`
- Or site-wide: `Site Administration -> Actions -> Runners`

Register the runner once (it stores its config in `./.forgejo-runner`):

```bash
docker compose -f docker-compose.forgejo.yml run --rm runner-register <TOKEN>
```

Then start the runner daemon:

```bash
docker compose -f docker-compose.forgejo.yml up -d runner
```

The runner uses the host Docker socket to spawn job containers, and advertises
the `docker` label that the workflow's `runs-on: docker` targets.

## 4. Trigger a run

Push a commit (or open a PR) to `main`. The workflow appears under the repo's
**Actions** tab and runs the test suite in a `catthehacker/ubuntu:act-latest`
container (Python + git + node + pip, matching the `ubuntu-latest` label the
runner is registered with).

## Notes

- Data persists in `./.forgejo-data` (Forgejo) and `./.forgejo-runner` (runner
  config); both are git-ignored.
- To stop everything: `docker compose -f docker-compose.forgejo.yml down`.
- The workflow file is portable: the same steps run on GitHub Actions
  (`.github/workflows/tests.yml`) and Forgejo (`.forgejo/workflows/tests.yml`).
  Keeping both lets the project build on either forge.
