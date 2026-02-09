# Changelog

All notable changes to the CapyDeploy Decky Plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

For the full CapyDeploy project changelog, see the [main project](https://github.com/lobinuxsoft/capydeploy/blob/master/CHANGELOG.md).

## [0.5.0](https://github.com/lobinuxsoft/decky-capydeploy/compare/v0.4.0...v0.5.0) (2026-02-09)


### Features

* add CI workflow and auto-submit to Decky Plugin Store ([56b1431](https://github.com/lobinuxsoft/decky-capydeploy/commit/56b14317dff74d55f61fad7c0e53e7fb6a8c38b3))
* add release-please for independent versioning ([349754f](https://github.com/lobinuxsoft/decky-capydeploy/commit/349754f06955992531c8c7adadf11c42f5c84635))
* **build:** unificar versionado con archivo VERSION como fuente única ([324d050](https://github.com/lobinuxsoft/decky-capydeploy/commit/324d050bc5a287c91e460d2ae9aa0ace01228834))
* **decky:** agregar soporte de artwork local al agente Decky ([ee9f394](https://github.com/lobinuxsoft/decky-capydeploy/commit/ee9f3949326e82370f8b12f00f4974a0aae5244f))
* **decky:** habilitar paneles colapsables con PanelSection title ([7daf0ca](https://github.com/lobinuxsoft/decky-capydeploy/commit/7daf0caceabe790a652a8ce19cb4f17f0dceb66d))
* **decky:** implementar paneles colapsables preservando estilo glass ([c81b186](https://github.com/lobinuxsoft/decky-capydeploy/commit/c81b186d64a99f27967c25e2b0418f300e7e6e9d))
* **decky:** persistir estado de paneles colapsables con usePanelState ([ec30c27](https://github.com/lobinuxsoft/decky-capydeploy/commit/ec30c27afe74a7af5b7eb9bbd8f9f6239442246e))
* prepare for Decky Plugin Store submission ([a7eda4c](https://github.com/lobinuxsoft/decky-capydeploy/commit/a7eda4c48e3cbc68e36cc3c4b4d2039941e66d4b))
* prepare for standalone repo and Decky Plugin Store ([3edd38e](https://github.com/lobinuxsoft/decky-capydeploy/commit/3edd38e49a3f9a82a172b15875f4afa40994928d))


### Bug Fixes

* **agent-decky:** aplicar Proton a .exe, reducir toasts y subir límite WS ([14ca829](https://github.com/lobinuxsoft/decky-capydeploy/commit/14ca8293bdf25e0e79291af3faacef55f27d24de))
* **core:** eliminar código muerto y corregir memory leaks ([3fcd356](https://github.com/lobinuxsoft/decky-capydeploy/commit/3fcd356a0d1903f9c22f55a201a5e34e7f73e8a7)), closes [#67](https://github.com/lobinuxsoft/decky-capydeploy/issues/67)
* **decky:** aplicar artwork via SteamClient API para visibilidad inmediata ([8e34be2](https://github.com/lobinuxsoft/decky-capydeploy/commit/8e34be28ed055fde92c198626f38c8a4b635ab98))
* **decky:** corregir flujo de artwork local para agente Decky ([170112e](https://github.com/lobinuxsoft/decky-capydeploy/commit/170112e9a2efb861e409958624c9072c3a39369e))
* **decky:** corregir memory leaks en plugin Decky ([64b3696](https://github.com/lobinuxsoft/decky-capydeploy/commit/64b3696b07ad37deed30ed931e589dc9e22f16c4))
* **decky:** leer versión desde package.json en vez de hardcodear ([e409ad4](https://github.com/lobinuxsoft/decky-capydeploy/commit/e409ad4559f05ac2de7f537646ff4f9b31208819)), closes [#81](https://github.com/lobinuxsoft/decky-capydeploy/issues/81)
* **decky:** mostrar juegos instalados sin conexión activa ([31fdd49](https://github.com/lobinuxsoft/decky-capydeploy/commit/31fdd49ae91ccf4f31e958903f9d64f85113074b)), closes [#82](https://github.com/lobinuxsoft/decky-capydeploy/issues/82)


### Refactoring

* centralizar outputs de build en dist/ ([a7764a8](https://github.com/lobinuxsoft/decky-capydeploy/commit/a7764a8d6a4960d0c96f63ff43f508b8b7332a9a))
* **core:** eliminar duplicados menores e implementar cleanup de uploads ([c270d8b](https://github.com/lobinuxsoft/decky-capydeploy/commit/c270d8b8b22ee05aac7abd0f320ec795dc88b6a6)), closes [#67](https://github.com/lobinuxsoft/decky-capydeploy/issues/67)
* eliminar campo capabilities redundante del protocolo ([70ad686](https://github.com/lobinuxsoft/decky-capydeploy/commit/70ad686c5f7285b30587e256b00c8c0e72fd702a))
* reorganizar estructura de agentes ([f082aca](https://github.com/lobinuxsoft/decky-capydeploy/commit/f082acaf108b77142e731ae3b60fe740d5ae62b8))


### Documentation

* add community files and GitHub templates ([08961b4](https://github.com/lobinuxsoft/decky-capydeploy/commit/08961b49c3186f218b6febc7c4cafc08c3b95c67))

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
