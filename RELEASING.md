# Releasing the Python SDK

This checklist is what you follow to cut a new PyPI release of
`declaw`. It assumes you are on an up-to-date `main` branch
with a clean working tree.

## Prerequisites

- [Poetry](https://python-poetry.org/) installed.
- A PyPI API token with upload rights to the `declaw` project, either
  in `~/.pypirc` or as the `POETRY_PYPI_TOKEN_PYPI` environment
  variable.

Configure once:

```bash
poetry config pypi-token.pypi <your-token>
# OR
export POETRY_PYPI_TOKEN_PYPI=<your-token>
```

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

2. **Verify**

   ```bash
   make test           # full test suite
   make typecheck      # mypy clean
   make lint           # ruff clean
   poetry check        # pyproject validation
   ```

3. **Build**

   ```bash
   poetry build
   ls -lh dist/        # expect declaw-X.Y.Z.tar.gz and declaw-X.Y.Z-py3-none-any.whl
   ```

4. **Dry-run inspection (optional but recommended)**

   ```bash
   tar -tzf dist/declaw-X.Y.Z.tar.gz | head     # sanity check what's shipped
   unzip -l dist/declaw-X.Y.Z-py3-none-any.whl  # check wheel contents
   ```

5. **Publish**

   ```bash
   poetry publish
   ```

   Verify on <https://pypi.org/project/declaw/>.

6. **Commit + push**

   ```bash
   git commit -am "release(python-sdk): vX.Y.Z"
   git push origin main
   ```

   Then publish a snapshot to the public mirror (`declaw-ai/declaw-python`;
   gated by junk/secret scans — the public repo gets one commit with this
   message, never internal history):

   ```bash
   gh workflow run sync-mirror.yml -f component=python-sdk \
     -f message="release(python-sdk): vX.Y.Z" && gh run watch
   ```

7. **Tag + release on the public repo**

   Release tags live only on the public mirror (bare `vX.Y.Z` — the
   monorepo carries no SDK tags; its `vX.Y.Z` namespace belongs to the
   platform release series):

   ```bash
   SHA=$(git ls-remote python-public main | cut -f1)
   gh api repos/declaw-ai/declaw-python/git/refs \
     -f ref=refs/tags/vX.Y.Z -f sha=$SHA
   gh release create vX.Y.Z --repo declaw-ai/declaw-python \
     --title "declaw vX.Y.Z" \
     --notes "<paste the CHANGELOG block for this version>"
   ```

## Yanking a bad release

If you need to pull a broken version:

```bash
# Mark as yanked on PyPI (keeps it installable for pinned users,
# prevents new resolvers from picking it).
poetry run pip-yank declaw X.Y.Z
```

Or via the PyPI web UI. Yanking is preferred over deletion; deletion
prevents re-uploading the same filename ever again.
