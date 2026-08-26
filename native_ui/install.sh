#!/bin/sh
# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
#
# One-time, idempotent on-device setup for the native touch-display UI: makes the kiosk launcher
# executable and registers it as an XFCE/XDG autostart entry for the current user, so it opens
# automatically every time an XFCE session starts. Run this once after pushing native_ui/ to the
# board (e.g. via `adb shell native_ui/install.sh` from the app's directory).
#
# This script deliberately does NOT touch anything that needs root -- activating the Media
# Carrier's display output, installing unclutter, and lightdm autologin all need an interactive
# sudo password this script can't supply non-interactively. Run native_ui/setup-sudo.sh once
# yourself for those; see the README's "Native touch-display UI" section.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"

chmod +x "$SCRIPT_DIR/launch-progq-kiosk.sh"

mkdir -p "$AUTOSTART_DIR"
cp "$SCRIPT_DIR/progq-kiosk.desktop" "$AUTOSTART_DIR/progq-kiosk.desktop"

echo "Installed. The kiosk will open automatically on the next XFCE login."
echo "If you haven't yet, also run 'sudo sh native_ui/setup-sudo.sh' once to activate the Media"
echo "Carrier's display and enable a keyboard-less autologin -- see the README's Native"
echo "touch-display UI section."
