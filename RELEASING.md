# Releasing the Python SDK

Checklist for cutting a new PyPI release of `declaw`. It assumes you are
on an up-to-date `main` branch with a clean working tree.

Publishing is automated: pushing a `vX.Y.Z` tag to the public mirror
(`declaw-ai/declaw-python`) triggers `publish.yml` there, which verifies
the tag against `pyproject.toml`, runs the test suite, builds, publishes
to PyPI via Trusted Publishing (OIDC — no token anywhere), and creates a
GitHub Release from the CHANGELOG block. The tag is the release button.

## Steps

1. **Bump version + update changelog**

   Edit `pyproject.toml`:

   ```toml
   [tool.poetry]
   version = "X.Y.Z"
   ```

   Add the new version block at the top of `CHANGELOG.md` following the
   [Keep a Changelog](https://keepachangelog.com/) format. Keep
   breaking changes grouped under `### Changed` and behavior additions
   under `### Added`. Bump the major when breaking the public API
   defined in `declaw/__init__.py`.

2. **Verify locally**

   ```bash
   make test           # full test suite
   make typecheck      # mypy clean
   make lint           # ruff clean
   poetry check        # pyproject validation
   ```

3. **Commit + push**

   ```bash
   git commit -am "release(python-sdk): vX.Y.Z"
   git push origin main
   ```

4. **Sync the public mirror** (gated by junk/secret scans; the mirror
   gets one commit with this message, never internal history)

   ```bash
   gh workflow run sync-mirror.yml -f component=python-sdk \
     -f message="release(python-sdk): vX.Y.Z" && gh run watch
   ```

5. **Tag the mirror — this publishes**

   Release tags live only on the public mirror (bare `vX.Y.Z` — the
   monorepo carries no SDK tags):

   ```bash
   SHA=$(git ls-remote python-public main | cut -f1)
   gh api repos/declaw-ai/declaw-python/git/refs \
     -f ref=refs/tags/vX.Y.Z -f sha=$SHA
   ```

   Watch the publish run
   (`gh run list --repo declaw-ai/declaw-python -w publish.yml`), then
   verify on <https://pypi.org/project/declaw/>. If it fails, nothing
   was published — fix the cause and `gh run rerun` (the tag stays).

## Yanking a bad release

```bash
# Mark as yanked on PyPI (keeps it installable for pinned users,
# prevents new resolvers from picking it).
poetry run pip-yank declaw X.Y.Z
```

Or via the PyPI web UI. Yanking is preferred over deletion; deletion
prevents re-uploading the same filename ever again.

## Manual fallback

If CI is unavailable: `poetry build && poetry publish` with a PyPI token
(`POETRY_PYPI_TOKEN_PYPI`), then create the tag + GitHub Release by hand.
