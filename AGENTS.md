# ChronoFox Agent Instructions

## Project

- Windows desktop app built with Python 3.13 and PySide6.
- Main entry point: `desktop_note_calendar.py`.
- Product name: `ChronoFox / 크로노폭스`.
- Previous/project folder name: `Fox Calendar`.

## Read First

- Read `planning/PROJECT.md` for product direction, roadmap, v1.0 scope, security notes, and collaboration rules.
- Read `planning/QA.md` before code changes. It is the active bug/review/verification log.

## Working Rules

- Do not revert unrelated dirty worktree changes.
- Preserve existing user data, memo files, settings, and path compatibility.
- Do not hardcode user-specific save paths.
- Ask before adding new runtime dependencies.
- Keep user-facing strings in both `locales/ko.json` and `locales/en.json`.
- Prefer project patterns and existing PySide6 helpers before adding new abstractions.
- Update `planning/QA.md` when resolving or verifying user-facing changes.
- When using team mode from planning/development rooms, record the result in the relevant markdown handoff and archive completed member threads after the work is done so the project tab does not keep accumulating agent threads.

## Verification

Use focused checks for the files touched, then broaden when the change affects shared behavior.

Common commands:

```powershell
python -m pytest -q
python -m py_compile desktop_note_calendar.py settings_window.py memo_window.py schedule_window.py todo_window.py clock_window.py clock\window.py clock\layout.py clock\alarm_dialog.py clock\styles.py clock\alarm_dialog_styles.py app_config.py app_design.py app_i18n.py app_ui.py app_models.py
python -m ruff check app_config.py app_ui.py app_design.py clock\window.py clock\layout.py clock\alarm_dialog.py clock\styles.py clock\alarm_dialog_styles.py settings_window.py desktop_note_calendar.py tests
```

For visual/UI changes, prefer direct app use or Qt offscreen captures. Store useful captures under `planning/ui_captures/`.

`basedpyright` can be noisy with PySide6 enums, mixins, and stubs. Treat it as supplementary unless the reported issue is clearly local and actionable.
