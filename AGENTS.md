# Agent notes for this fork

Fork of [Plesuro/MoldForge](https://github.com/Plesuro/MoldForge) (remote `upstream`),
a Blender 5.1+ extension (GPL-3.0-or-later). Our fork is `origin`.

## Workflow

- Work on a feature branch, never directly on `main`.
- When the work is done and **both test suites pass**, you are cleared to merge it
  into `main` and push without asking. If any test fails, stop and report instead.
- Add an entry under "Unreleased" in `CHANGELOG.md` for user-facing changes. Leave
  the version in `blender_manifest.toml` alone unless asked.

## Tests

Run from the folder that contains the `moldforge` checkout (the tests import it as
`moldforge`), with Blender 5.1:

    blender --background --python-exit-code 1 --python moldforge/tests/test_register.py
    blender --background --python moldforge/tests/test_headless.py

Without a Blender install, `pip install bpy==5.1.2` (Python 3.13) and run each file
with that Python instead. The headless suite takes about 4 minutes.

## Conventions

- Files use CRLF line endings; keep them (check `git diff --stat` for whole-file churn).
- Sizes are plain floats in millimetres (`_dist` in `properties.py`); add new length
  properties to the list in `core/units.py`, and pass new settings through the
  namespace in `core/pipeline.py`.
- Don't rename existing properties: saved presets are keyed by property name.
  Relabel them with `name=` instead.
- New geometry steps are best-effort with rollback: a feature that would leave a
  part invalid is skipped with a note, never breaks the mold.
