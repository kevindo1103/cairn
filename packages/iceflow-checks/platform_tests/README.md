# Native Windows acceptance (separate from portable/synthetic tests)

Run `python scripts/validate_windows.py --out .review/windows-new` from the Harness
repo after installing its wheel and pytest in an isolated venv. The command requires
Windows, a real junction and filesystem symlinks. It does not change OS privileges.
Missing capability -> exit 2 / NOT_RUN; never skip to obtain a green count.

The default `pytest` path is `tests/` (portable tests, including real filesystem
symlinks on a capable host and synthetic Windows attribute cases). This alone is
NOT Windows acceptance. The Windows runner adds all 13 native junction/symlink
cases from `platform_tests/windows/` and rejects a missing/empty/skipped lane.

The source-link test in the portable suite constructs Git mode 120000 directly;
it tests Git blob-mode refusal without confusing OS symlink setup with its oracle.
Actual filesystem symlink rejection is still tested in the audio test, path tests,
and in the explicit native Windows lane.
