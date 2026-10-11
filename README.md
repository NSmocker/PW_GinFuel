# Clean Arch

This is the GUI-only rewrite of the client.

## Boundaries

- `clean_arch/domain`: data models and ports; no DearPyGUI, sockets, or legacy imports.
- `clean_arch/application`: use-case orchestration and log presentation policy.
- `clean_arch/infrastructure`: process, configuration, OS, wire codecs, and TCP transport.
- `worker_entry.py`: one account session per subprocess.
- `gui_app.py`: DearPyGUI presentation and tab lifecycle.

The production worker uses the clean wire/session implementation directly.

The Windows identity probes and configuration parsers are still adapters to the
original modules because their compatibility depends on the deployed machine
and server environment.

## Protocol diagnostics

When the source checkout is available, the worker loads protocol names from
`CElement/CElementClient/Network/callid.hxx`, `EC_GPDataType.h`, and
`gnetdef.h`. Console lines include direction, numeric ID, source symbol, and
payload size. Set `client_source_root=` in the config if the checkout is in a
different location. Localized text for message IDs still requires the game's
string-table assets; source headers provide the authoritative numeric names.

Optional parsed-data paths can enrich diagnostics:
`game_client_root=`, `elements_root=`, and `tasks_root=`. The latter two point
to JSON exports and are loaded lazily.

The three STF files may be placed directly beside the config file. The loader
also accepts the original `Interfaces\\MsgBox.stf` layout.

Run `start_clean_gui.bat` from Windows, or `python gui_app.py` from this folder.
