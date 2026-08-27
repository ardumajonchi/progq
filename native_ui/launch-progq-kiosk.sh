#!/bin/sh
# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
#
# Native touch-display UI: opens the same web UI the browser uses, full-screen and chrome-free, on
# whatever display this XFCE session owns (the Waveshare 5" DSI-TOUCH-A on the Media Carrier's DSI
# port, if that's what's attached). It is just another client of the app's own Socket.IO server --
# no separate UI implementation, so it can never drift from the browser's look or behavior, and it
# keeps working alongside the browser exactly like the AI Operator and physical controls already do.
set -eu

URL="http://127.0.0.1:7000/"
DEBUG_PORT=9223
CHECK_INTERVAL_S=10
BAD_CHECKS_BEFORE_RESTART=2

# Appliance-style display: never blank/sleep the panel.
xset s off || true
xset s noblank || true
xset -dpms || true

# Hide the mouse cursor if unclutter happens to be installed; skip silently otherwise -- same
# degrade-safe spirit as every optional peripheral elsewhere in this app.
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0 &
fi

# arduino-app-cli does not auto-start apps on boot -- after a reboot the app container simply isn't
# running until something starts it, which is why the kiosk would otherwise come up pointed at a
# dead port. Best-effort start it ourselves so the kiosk is fully self-sufficient; ignore the error
# this prints if the app (or App Lab) already started it first.
arduino-app-cli app start user:progq >/dev/null 2>&1 || true

# The app container can take a few seconds to come up after boot; wait for it instead of racing it.
for _ in $(seq 1 60); do
  if curl --max-time 1 -s -o /dev/null "$URL"; then
    break
  fi
  sleep 1
done

launch_chromium() {
  chromium \
    --kiosk "$URL" \
    --start-fullscreen \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --touch-events=enabled \
    --incognito \
    --remote-debugging-port="$DEBUG_PORT" \
    --check-for-update-interval=31536000 &
  chromium_pid=$!
}

stop_chromium() {
  kill "$chromium_pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    kill -0 "$chromium_pid" 2>/dev/null || return 0
    sleep 1
  done
  kill -9 "$chromium_pid" 2>/dev/null || true
}

# Chromium's own remote-debugging endpoint (bound to localhost only) is the only reliable way to
# see what's actually on screen: a renderer crash leaves the top-level process untouched and
# --noerrdialogs suppresses the crash bubble, so it silently lands on the New Tab Page instead of
# the app with nothing to show anything is wrong. `kill -0` on the main PID can't catch that.
current_url() {
  curl --max-time 2 -s "http://127.0.0.1:$DEBUG_PORT/json" 2>/dev/null \
    | jq -r '[.[] | select(.type == "page")][0].url // ""' 2>/dev/null
}

launch_chromium
bad_checks=0

while true; do
  sleep "$CHECK_INTERVAL_S"

  if ! kill -0 "$chromium_pid" 2>/dev/null; then
    launch_chromium
    bad_checks=0
    continue
  fi

  case "$(current_url)" in
    "$URL"*)
      bad_checks=0
      ;;
    *)
      bad_checks=$((bad_checks + 1))
      if [ "$bad_checks" -ge "$BAD_CHECKS_BEFORE_RESTART" ]; then
        stop_chromium
        launch_chromium
        bad_checks=0
      fi
      ;;
  esac
done
