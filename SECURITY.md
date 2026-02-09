# Security Policy

> This plugin is part of [CapyDeploy](https://github.com/lobinuxsoft/capydeploy). For security concerns affecting the overall project, please refer to the [main project's security policy](https://github.com/lobinuxsoft/capydeploy/blob/master/SECURITY.md).

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest | Yes |
| Older | No |

As an early-stage project, only the latest version receives updates.

## Reporting a Concern

If you discover a potential security issue, please report it responsibly:

1. **Do NOT** open a public issue
2. **Do** contact the maintainer privately via [GitHub Discussions](https://github.com/lobinuxsoft/capydeploy/discussions) (private message) or email
3. Include as much detail as possible to help reproduce and understand the issue

## Response Timeline

- **Acknowledgment**: Within 72 hours
- **Initial assessment**: Within 1 week
- **Resolution timeline**: Depends on complexity, communicated after assessment

## Scope

This policy applies to:
- The Decky plugin Python backend (WebSocket server, pairing, uploads)
- The React/TypeScript frontend running inside Decky Loader
- Pairing token storage and management
- File upload handling and Steam shortcut creation

**Out of scope**:
- Decky Loader itself — report to [SteamDeckHomebrew/decky-loader](https://github.com/SteamDeckHomebrew/decky-loader)
- CapyDeploy Hub — report to [lobinuxsoft/capydeploy](https://github.com/lobinuxsoft/capydeploy)
- Third-party dependencies — report to their respective projects

## Security Considerations

This plugin handles:
- **Pairing tokens**: Stored locally in `~/homebrew/settings/capydeploy.json`
- **WebSocket connections**: From CapyDeploy Hub on the local network
- **File uploads**: Game files received and written to disk
- **Steam shortcuts**: Modification of Steam configuration via SteamClient APIs

### Best Practices for Users

1. Only pair with devices you trust on your local network
2. Keep Decky Loader and the plugin updated
3. Review connected hubs periodically in the plugin panel

## Recognition

Contributors who responsibly report valid issues will be credited in release notes (unless they prefer anonymity).
