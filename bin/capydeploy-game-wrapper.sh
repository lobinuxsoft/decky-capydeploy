#!/bin/bash
# CapyDeploy Game Wrapper — captures stdout/stderr to a log file.
# Injected into Steam launch options as:
#   /path/to/capydeploy-game-wrapper.sh APPID %command%
#
# First argument is the Steam appId (passed by the injector so non-Steam
# shortcuts get the correct ID instead of relying on $SteamAppId which is 0).
#
# Uses stdbuf for line-buffered output so logs are available in real-time.
# The log file path is predictable: game_{APPID}_{TIMESTAMP}.log

APPID="${1:-unknown}"
shift

LOG_DIR="${HOME}/.local/share/capydeploy/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/game_${APPID}_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

# Run the game with line-buffered output, tee to log file AND original stdout.
# stdbuf forces line-buffering so the tailer sees lines in real-time.
stdbuf -oL -eL "$@" 2>&1 | tee -a "$LOG_FILE"
