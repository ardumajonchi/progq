# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Printer tape formatting: renders keystrokes and computed results as tape lines, matching the
real machine's 30-column printer and the instruction symbols shown on EMU101's tape display.
Clean-room formatting logic, not a port of any existing emulator's rendering code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TAPE_WIDTH = 30

DISPLAY_SYMBOLS = {
    "add": "+",
    "sub": "-",
    "mul": "x",
    "div": "÷",
    "sqrt": "√",
    "transfer_to_m": "↓",
    "exchange_a": "Â",
    "decimal_part": ".",
    "clear": "✳",
    "print": "◇",
    "stop": "S",
    "rs": "RS",
    "jump": "→",
    "cond_jump": "↦",
}


@dataclass
class Tape:
    """An append-only log of printed lines, feeding both the UI's scrolling tape display and the
    "Share Tape" export."""

    lines: list[str] = field(default_factory=list)

    def echo_key(self, operator: str, register: str | None = None) -> None:
        symbol = DISPLAY_SYMBOLS.get(operator, operator)
        line = f"{register}{symbol}" if register else symbol
        self.lines.append(line.ljust(TAPE_WIDTH)[:TAPE_WIDTH].rstrip())

    def print_value(self, value: str, register: str | None = None) -> None:
        label = f"{register} " if register else ""
        self.lines.append(f"{label}{value}"[:TAPE_WIDTH])

    def clear(self) -> None:
        self.lines = []

    def as_text(self) -> str:
        return "\n".join(self.lines)
