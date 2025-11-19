# Repository Guidelines

## Project Structure & Module Organization
`whatsapp_converter.py` is the CLI entry and delegates to `chat_exporter/` modules: parsing (`parser.py`), message models (`models.py`), media helpers (`media.py`), rendering (`renderer.py`, `html/` assets), and orchestration (`exporter.py`). Selenium automation lives in `group_extractor/` with its own `config.py`. Conversion artifacts default to `html/`, while sanitized fixtures for regression work live in `example/` and `defiScam_*`.

## Build, Test, and Development Commands
- `python3 -m venv venv && source venv/bin/activate`: create an isolated environment.
- `pip install -r requirements.txt`: install Selenium and WebDriver Manager.
- `python whatsapp_converter.py convert example/WhatsApp\ Chat\ -\ DeFi\ Farming\ Club\ V3_desktop.zip -o html`: convert a sample export into `html/`.
- `python whatsapp_converter.py update <new_export.zip> -o html --highlight subtle`: merge incremental exports.
- `python group_extractor/main.py`: run the WhatsApp Web automation (requires a configured Chrome profile).

## Coding Style & Naming Conventions
Stick to PEP 8, 4-space indentation, and snake_case names as seen in `chat_exporter/models.py`. Keep docstrings on public helpers, reuse the configured logger, and prefer type hints in new code. When editing templates, reuse the existing class names and dark/light toggle hooks. Format touched Python files with `python -m black whatsapp_converter.py chat_exporter` before sending a PR, and keep argparse help text in sync with actual behavior.

## Testing Guidelines
There is no automated suite yet, so rely on the ZIP fixtures inside `example/` and the committed `defiScam_*` exports. For parser/renderer changes run both `convert` and `update`, then spot-check `whatsapp_chat.html`, `chat_data.json`, and `metadata.json`. Selenium work should be tested with a disposable WhatsApp Web session, with logs or screenshots attached to the PR if bugs arise. If you add scripted tests, place them under `tests/` and run them with `pytest`.

## Commit & Pull Request Guidelines
Follow the existing prefixes visible in `git log` (`new: scope: summary`, `chg: scope: detail`). Keep commits focused, reference issue IDs, and note whether the change touches the exporter or Selenium agent. Pull requests should provide a short narrative, the manual commands executed, and screenshots or GIFs whenever rendered HTML changes. Confirm that no personal chat data or secrets are included in artifacts or diffs.

## Security & Data Handling
Only work with sanitized sample exports; never push personal conversations or Chrome profile data. Keep `group_extractor/config.py` untracked and point it to a dedicated browser profile. When sharing debugging assets, redact phone numbers and message IDs within `metadata.json` or encrypt the archive before transfer.
