# OpenCarStream Menu Bar App

This is a native macOS menu-bar controller for the `opencarstream` CLI. It
starts/stops/restarts the server process, opens the dashboard, exposes basic
server settings, polls `/health`, and writes server logs under the configured
app support directory.

Expected CLI path after Homebrew install:

```bash
/opt/homebrew/bin/opencarstream
```

Build path:

```bash
scripts/build_macos_app.sh 0.1.0
```

This produces:

```text
dist/OpenCarStream-0.1.0.dmg
```

The app should be signed and notarized before public distribution.

The app intentionally delegates streaming to the CLI instead of embedding server
logic. That keeps Docker, CLI, launchd, and menu-bar app behavior aligned.
