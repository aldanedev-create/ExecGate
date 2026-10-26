
# scripts/

Dev/CI tools. Not shipped in the wheel, not on the user's PATH.

All scripts are `python -m stdlib_only` — pure standard library except
`publish.py` and `preflight.py`, which need `build` and `twine`
(installed via `pip install -e ".[dev]"`).

| Script | Purpose |
|---|---|
| `check_imports.py` | Fail if `src/logiq/` imports anything outside stdlib |
| `clean.py` | Remove build artifacts and caches |
| `verify_wheel.py` | Inspect a built wheel: contents, `py.typed`, no runtime deps |
| `preflight.py` | Run all checks that must pass before publishing |
| `publish.py` | Build, check, upload to PyPI or TestPyPI |
| `release.py` | Bump version, update changelog, git commit + tag |

## Typical release flow

```bash
# 1. Bump the version and update the changelog
python scripts/release.py --patch

# 2. Push the commit and tag
git push origin main --tags

# 3. Test on TestPyPI first
python scripts/publish.py --test

# 4. Verify install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ logiq

# 5. Publish to real PyPI
python scripts/publish.py
Running checks individually
bash
python scripts/check_imports.py     # fast, catches accidental deps
python scripts/preflight.py         # everything, before publish
python scripts/clean.py             # before rebuilding
```