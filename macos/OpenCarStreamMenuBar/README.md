# OpenCarStream Menu Bar App

This is a thin native macOS menu-bar controller for the `opencarstream` CLI.
It starts and stops the server process, opens the dashboard, and stores basic
server settings in `UserDefaults`.

Expected CLI path after Homebrew install:

```bash
/opt/homebrew/bin/opencarstream
```

Build path:

1. Create a new macOS SwiftUI app target in Xcode.
2. Replace the generated app source with `OpenCarStreamMenuBarApp.swift`.
3. Set the app category to `public.app-category.video`.
4. Archive, sign, notarize, and distribute the `.app` through a Homebrew cask.

The app intentionally delegates streaming to the CLI instead of embedding server
logic. That keeps Docker, CLI, launchd, and menu-bar app behavior aligned.
