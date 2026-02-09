# CapyDeploy Decky Plugin

<div align="center">
  <img src="assets/mascot.gif" alt="CapyDeploy" width="200">

  **Receive games from your PC in gaming mode — no Steam restart needed.**

  [![License](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
  [![Decky Loader](https://img.shields.io/badge/Decky%20Loader-Plugin-blue)](https://decky.xyz/)
  [![CapyDeploy](https://img.shields.io/badge/Part%20of-CapyDeploy-orange)](https://github.com/lobinuxsoft/capydeploy)
</div>

> **This plugin is part of [CapyDeploy](https://github.com/lobinuxsoft/capydeploy)** — a cross-platform tool for deploying games to Steam Deck and other handheld Linux devices. It requires the CapyDeploy Hub running on your PC.

## What is This?

A [Decky Loader](https://decky.xyz/) plugin that acts as a CapyDeploy Agent inside **gaming mode**. While the desktop Agent requires switching to desktop mode, this plugin runs natively in the Quick Access Menu — receive games, create shortcuts, and apply artwork without leaving your game library.

### Features

- **No Steam restart** — Creates shortcuts using native `SteamClient.Apps` APIs
- **Instant artwork** — Applies cover art, icons, and heroes via `SteamClient.Apps.SetCustomArtworkForApp()`
- **Toggle On/Off** — Enable/disable the WebSocket connection from the QAM panel
- **Auto-connect** — Reconnects automatically when enabled
- **Real-time notifications** — Toast notifications for game installs
- **Progress tracking** — See transfer progress in the panel
- **Secure pairing** — 6-digit code on first connection, token stored for future sessions

### How It Compares

| Feature | Desktop Agent (Wails) | Decky Plugin |
|---------|----------------------|--------------|
| Shortcuts | `shortcuts.vdf` (restart Steam) | `SteamClient.Apps.AddShortcut()` (instant) |
| Artwork | File copy to `grid/` | `SteamClient.Apps.SetCustomArtworkForApp()` |
| UI | Standalone window | Quick Access Menu panel |
| Mode | Desktop | Gaming |

## Requirements

- Steam Deck or other handheld running SteamOS/Bazzite
- [Decky Loader](https://decky.xyz/) installed
- [CapyDeploy Hub](https://github.com/lobinuxsoft/capydeploy/releases) running on your PC

## Installation

### From Decky Store (Recommended)

1. Open Decky Loader (... button in gaming mode)
2. Go to the Plugin Store
3. Search for "CapyDeploy"
4. Click Install

### Manual Installation

1. Download the latest `CapyDeploy-Decky.zip` from [CapyDeploy releases](https://github.com/lobinuxsoft/capydeploy/releases)
2. Extract to `~/homebrew/plugins/`
3. Restart Decky Loader

## Usage

1. Open the Quick Access Menu (... button)
2. Find CapyDeploy in the Decky plugins list
3. Toggle the plugin **ON**
4. On your PC, open CapyDeploy Hub — it will discover the plugin via mDNS
5. If this is your first connection, enter the 6-digit pairing code shown in the Hub
6. Start sending games from the Hub!

## Architecture

```
Hub (PC) ──WebSocket──► Decky Plugin (Handheld)
                              │
                              ├─► SteamClient.Apps.AddShortcut()
                              ├─► SteamClient.Apps.SetCustomArtworkForApp()
                              └─► Toast notifications
```

The plugin runs a WebSocket server that speaks the same protocol as the desktop Agent. The Hub doesn't need to know which type of agent it's talking to — the protocol is identical.

## Building from Source

### Requirements

- Node.js 18+ (with npm or pnpm)
- Python 3.11+ (for backend dependencies)

### Build

```bash
# Install frontend dependencies
pnpm install    # or npm install

# Build frontend
pnpm build      # or npm run build

# Full build with Python deps and ZIP packaging (Linux only)
./build.sh
```

### Development

```bash
# Watch mode (auto-rebuild on changes)
pnpm watch      # or npm run watch
```

### Project Structure

```
decky-capydeploy/
├── main.py             # Python backend — Decky API entry point
├── steam_utils.py      # Steam helpers (platform detection, VDF parsing)
├── mdns_service.py     # mDNS/DNS-SD advertisement
├── pairing.py          # Pairing codes + token management
├── upload.py           # UploadSession data class
├── artwork.py          # Artwork download + icon VDF writing
├── ws_server.py        # WebSocket server for Hub connections
├── src/
│   ├── index.tsx       # React UI entry point
│   ├── eventPoller.tsx # Background polling + SteamClient operations
│   ├── components/     # React components (StatusPanel, InstalledGames, etc.)
│   ├── hooks/          # Custom hooks (useAgent, usePanelState)
│   ├── styles/         # Theme constants
│   └── types.ts        # TypeScript type definitions
├── plugin.json         # Decky plugin manifest
├── package.json        # Node.js dependencies
├── rollup.config.mjs   # Rollup build configuration
├── build.sh            # Build + packaging script
└── requirements.txt    # Python dependencies
```

## Relationship with CapyDeploy

This repo contains **only the Decky Loader plugin**. It is maintained as a standalone repository because the [Decky Plugin Store](https://plugins.deckbrew.xyz/) requires plugins to be in their own repos (referenced as git submodules).

- **Main project**: [lobinuxsoft/capydeploy](https://github.com/lobinuxsoft/capydeploy)
- **Issues & discussions**: Please use the [main project's issues](https://github.com/lobinuxsoft/capydeploy/issues) for bugs and feature requests
- **Documentation**: [lobinuxsoft.github.io/capydeploy](https://lobinuxsoft.github.io/capydeploy)

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Since this plugin is part of the CapyDeploy ecosystem, major changes should be discussed in the [main project](https://github.com/lobinuxsoft/capydeploy/issues) first.

## License

AGPL-3.0 — See [LICENSE](LICENSE) for details.

## Support

If you find CapyDeploy useful, consider supporting development:

- **BTC**: `bc1qkxy898wa6mz04c9hrjekx6p0yht2ukz56e9xxq`
- **USDT (TRC20)**: `TF6AXBP3LKBCcbJkLG6RqyMsrPNs2JCpdQ`
- **USDT (BEP20)**: `0xd8d2Ed67C567CB3Af437f4638d3531e560575A20`
- **Binance Pay**: `78328894`
