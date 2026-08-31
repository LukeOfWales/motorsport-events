# Contributing

Thanks for your interest in improving Motorsport Events! Contributions are
welcome — especially new event sources.

## Adding an event source

This is the most valuable contribution. The full step-by-step guide lives in the
README: **[Contributing a source](README.md#contributing-a-source)**. In short:

1. Add an adapter in `app/adapters/` (subclass `Adapter`, implement `fetch()`
   + a testable `parse()`).
2. Register it in `app/adapters/__init__.py`.
3. Add a test with a saved fixture in `tests/`.
4. Verify with `python -m app.build_site` and open a PR.

Prefer structured data (iCal / JSON-LD) over scraping HTML where a source
offers it — see `app/adapters/pembrey.py` and `app/adapters/msuk.py`.

## Development setup

```bash
pip install -r requirements-dev.txt
./scripts/install-hooks.sh   # pre-push hook runs the tests
pytest
```

## Ground rules

- Keep adapters resilient: skip a malformed item rather than failing the whole
  feed.
- Include a fixture + test with any new adapter so the parser stays covered when
  the source's markup changes.
- Tests must pass (`pytest`). CI runs them on every PR; the `main` branch
  requires them to pass before merge.
- Match the existing style — no new dependencies without good reason.

## Reporting issues

- **Suggest a source** or **report a bug** using the issue templates.
- For a source that's scraped but breaking, please include the source URL and
  what changed if you know.

By contributing you agree your work is licensed under the project's
[MIT License](LICENSE).
