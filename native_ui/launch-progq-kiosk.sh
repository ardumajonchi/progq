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

# Appliance-style display: never blank/sleep the panel.
xset s off || true
xset s noblank || true
xset -dpms || true

# Hide the mouse cursor if unclutter happens to be installed; skip silently otherwise -- same
# degrade-safe spirit as every optional peripheral elsewhere in this app.
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0 &
fi

# The app container can take a few seconds to come up after boot; wait for it instead of racing it.
for _ in $(seq 1 60); do
  if curl --max-time 1 -s -o /dev/null "$URL"; then
    break
  fi
  sleep 1
done

exec chromium \
  --kiosk "$URL" \
  --start-fullscreen \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --touch-events=enabled \
  --incognito \
  --check-for-update-interval=31536000
