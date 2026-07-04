# ChronoFox Agent Instructions

## 모델 사용 정책 (중요 / IMPORTANT)

- Fable(`claude-fable-5`)은 토큰 소모가 크다. **Fable 세션에서는 판단·설계·리뷰·사용자와의 결정만 직접 수행한다.**
- **코딩, 반복 수정, 테스트 실행, 캡처 생성, 문서 정리 같은 잡무는 서브에이전트(Agent 도구)를 하위 모델로 지정해 위임한다.**
  - 일반 코딩/수정: `model: "sonnet"`
  - 단순 반복/기계적 작업: `model: "haiku"`
- 위임한 결과물의 검토/승인 판단은 Fable이 직접 한다.

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
