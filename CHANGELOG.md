# Changelog

All notable changes to the CapyDeploy Decky Plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

For the full CapyDeploy project changelog, see the [main project](https://github.com/lobinuxsoft/capydeploy/blob/master/CHANGELOG.md).

## [0.4.0] - 2025-01-XX

### Added
- Initial standalone release (extracted from [capydeploy](https://github.com/lobinuxsoft/capydeploy) monorepo)
- WebSocket server for Hub connections
- Secure pairing with 6-digit codes and token persistence
- Game file upload with chunked transfer and progress tracking
- Steam shortcut creation via `SteamClient.Apps.AddShortcut()`
- Artwork application via `SteamClient.Apps.SetCustomArtworkForApp()`
- mDNS/DNS-SD advertisement for auto-discovery
- Toast notifications for game installs
- Collapsible panel state persistence across QAM open/close
- Hub authorization management (view and revoke)
- Installed games list with delete support
