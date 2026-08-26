#!/bin/sh
# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
#
# One-time, on-device setup for everything the native touch-display UI needs that requires root:
# activating the Media Carrier's DSI display output, installing the optional cursor-hiding
# package, and enabling XFCE autologin so the kiosk comes up with no keyboard attached. This is
# deliberately kept separate from install.sh, which runs unprivileged as the `arduino` user --
# `arduino-linux-config carrier enable`, `apt-get install`, and lightdm's config both need root,
# and root on this board needs an interactive password, so this script can't be driven
# non-interactively over `adb shell` the way install.sh can. Run it once yourself, at the board's
# console, over SSH, or via an interactive `adb shell` session (not a one-line `adb shell "..."`):
#
#   sudo sh native_ui/setup-sudo.sh [display-option]
#
# display-option defaults to 5-dsi-touch-a (the Waveshare 5" DSI-TOUCH-A this app was built and
# tested against). Run `arduino-linux-config carrier list` to see every option your Media Carrier
# revision supports (e.g. 8-dsi-touch-a, 10-dsi-touch-a for the larger Waveshare panels).
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo: sudo sh native_ui/setup-sudo.sh" >&2
  exit 1
fi

DISPLAY_OPTION="${1:-5-dsi-touch-a}"
ARDUINO_USER="${SUDO_USER:-arduino}"

echo "==> Activating the Media Carrier's display output (${DISPLAY_OPTION})..."
arduino-linux-config carrier enable media-carrier "display=${DISPLAY_OPTION}"

echo "==> Installing unclutter (hides the mouse cursor in kiosk mode; safe to skip if unavailable)..."
apt-get update -qq || echo "    (apt-get update failed -- continuing, unclutter may already be cached)"
apt-get install -y unclutter || echo "    (unclutter install failed -- kiosk still works, just with a visible cursor)"

echo "==> Enabling XFCE autologin for user '${ARDUINO_USER}' (needed for a keyboard-less touch kiosk)..."
mkdir -p /etc/lightdm/lightdm.conf.d
printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\n' "$ARDUINO_USER" \
  > /etc/lightdm/lightdm.conf.d/50-progq-kiosk-autologin.conf
systemctl restart lightdm

echo
echo "Done. The Media Carrier display change takes effect on the next reboot -- reboot the board"
echo "now (or after also running native_ui/install.sh) for the touch panel and kiosk autologin to"
echo "come up together."
