# Contributing to CapyDeploy Decky Plugin

Thank you for your interest in contributing! This plugin is part of the [CapyDeploy](https://github.com/lobinuxsoft/capydeploy) project.

## Important: Where to Report Issues

This repo contains only the Decky Loader plugin. For bugs, feature requests, and discussions, please use the **main project**:

- **Bugs**: [capydeploy/issues](https://github.com/lobinuxsoft/capydeploy/issues)
- **Features**: [capydeploy/issues](https://github.com/lobinuxsoft/capydeploy/issues)
- **Questions**: [capydeploy/discussions](https://github.com/lobinuxsoft/capydeploy/discussions)

## Quick Reference

| Item | Value |
|------|-------|
| PRs target | `main` branch |
| Commit language | English |
| Commit format | [Conventional Commits](https://www.conventionalcommits.org/) |
| Code comments | English |

## Development Workflow

```
Create Issue (main repo) → Branch → Develop → PR → Review → Merge
```

### Branch Naming

```
feature/issue-XX-short-description
fix/issue-XX-short-description
docs/short-description
```

### Commit Messages

Write commits in **English** using Conventional Commits format:

```
feat: add artwork cache
fix: fix WebSocket reconnection logic
docs: update installation guide
refactor: simplify pairing flow
```

| Type | Use for |
|------|---------|
| `feat` | New features |
| `fix` | Bug fixes |
| `docs` | Documentation only |
| `refactor` | Code changes that neither fix bugs nor add features |
| `test` | Adding or updating tests |
| `chore` | Maintenance tasks |
| `build` | Build system changes |

## Code Standards

### TypeScript (Frontend)

| Item | Convention |
|------|------------|
| Components | PascalCase (`StatusPanel.tsx`, `InstalledGames.tsx`) |
| Files | camelCase for non-components (`eventPoller.tsx`, `types.ts`) |
| Variables/Functions | camelCase |
| Types/Interfaces | PascalCase |
| Private fields | `#private` |

### Python (Backend)

| Item | Convention |
|------|------------|
| Files | snake_case (`steam_utils.py`, `ws_server.py`) |
| Classes | PascalCase (`UploadSession`, `Plugin`) |
| Functions/Variables | snake_case (`get_local_ip`, `detect_platform`) |
| Private | `_prefix` |

### General Guidelines

- **Comments**: Write in English
- **Security**: Never log credentials or pairing tokens
- **Error handling**: Wrap errors with context

## Building

```bash
# Install dependencies
pnpm install    # or npm install

# Build frontend
pnpm build      # or npm run build

# Watch mode
pnpm watch      # or npm run watch

# Full build with ZIP packaging (Linux only)
./build.sh
```

## Pull Requests

1. **Target branch**: `main`
2. **Title**: Clear description of the change
3. **Body**: Reference the issue from the main repo if applicable
4. **Size**: Keep PRs focused and reviewable

## License

By contributing, you agree that your contributions will be licensed under the AGPL v3.
