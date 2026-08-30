# Local Forgejo Actions (CI) setup

This project keeps a Forgejo Actions workflow at `.forgejo/workflows/tests.yml`,
mirroring the GitHub Actions one. Forgejo Actions is largely GitHub-compatible,
so the same workflow syntax works with minor differences (the runner label and
container image).

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
a remote and push:

```bash
git remote add forgejo http://localhost:3000/<you>/motorsport-events.git
git push forgejo main
```

Forgejo detects `.forgejo/workflows/` automatically once Actions is enabled
(it is, via `FORGEJO__actions__ENABLED=true` in the compose file).

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
