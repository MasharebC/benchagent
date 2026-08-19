#!/bin/sh
# Human-facing live view of a BenchAgent session.
#
# Open this in its own Terminal window and leave it running. Everything the
# bench does -- step narration, build output, raw serial from the board --
# lands in runs/live.log and scrolls past here as it happens.
#
# Ctrl-C only stops watching. It never stops the work.

REPO=$(cd "$(dirname "$0")/.." && pwd)
LOG="$REPO/runs/live.log"

mkdir -p "$REPO/runs"
: >>"$LOG"

printf '\033]0;BenchAgent live\007'
clear
printf '=== BenchAgent live log ===\n'
printf 'watching: %s\n' "$LOG"
printf 'Ctrl-C stops watching, not the work.\n\n'

exec tail -n 40 -F "$LOG"
