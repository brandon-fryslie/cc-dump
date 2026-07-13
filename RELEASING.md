# Releasing cc-dump

How to cut a new release to [PyPI](https://pypi.org/project/cc-dump/). The mechanical
build-and-upload step is `just publish`; this document covers the surrounding steps that
need human judgment and can't be safely automated.

## Prerequisites (one-time)

- A PyPI account with maintainer access to the `cc-dump` project.
- A PyPI API token stored in `~/.pypirc`:

  ```ini
  [pypi]
  username = __token__
  password = pypi-<your-token>
  ```

  `twine` reads this automatically. (`uv publish` does **not** read `~/.pypirc`, which is
  why the recipe uses `twine`.)

## Steps

### 1. Pick and set the new version

Edit `version` in `pyproject.toml`. Follow semver against the last published version.

PyPI releases are **immutable**: once `X.Y.Z` is uploaded it can never be replaced or
re-uploaded, and the number can't be reused. Every release therefore needs a fresh version.
`just publish` refuses to upload a version that already exists on PyPI, so a forgotten bump
fails early instead of erroring mid-upload.

### 2. Land the bump on `master` via a PR

`master` is guarded by a repository ruleset — direct `git push origin master` is rejected.
Open a PR with the version bump (and any release-note/README changes):

```bash
git checkout -b release-<version>
git commit -am "Bump version to <version>"
git push -u origin release-<version>
gh pr create --base master --fill
```

CI runs `lint`, `mypy-changed-files`, `coverage`, and `test (3.10)`. **CI is the reviewer** —
there is no automated AI code-review workflow on this repo, and no required human approval.
Merge once the checks are green:

```bash
gh pr merge <pr> --squash --delete-branch
git checkout master && git pull --rebase origin master
```

### 3. Publish to PyPI

From the up-to-date `master` (clean tree):

```bash
just publish
```

This cleans `dist/`, builds the sdist + wheel (`uv build`), runs `twine check`, and uploads
with `twine`. It aborts if the tree is dirty or the version is already published.

### 4. Verify

`just publish` prints the version-specific PyPI URL. A release is confirmed live when that
endpoint returns HTTP 200:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/cc-dump/<version>/json
```

Check the version-specific endpoint, not `https://pypi.org/pypi/cc-dump/json` — the latter's
`info.version` field lags behind due to index caching and can show the old version for a while.

Then confirm a clean install resolves:

```bash
uv tool install "git+https://github.com/brandon-fryslie/cc-dump.git"
```

## Notes

- `snarfx`, cc-dump's own dependency, is published separately on PyPI. Releasing cc-dump does
  not touch it; if a release depends on unreleased snarfx changes, publish snarfx first.
