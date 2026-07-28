# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Menu-driven state machine for the optional physical control surface (Modulino Joystick +
Modulino Buttons). Deliberately knows nothing about `Machine`/`Tape` directly -- it only ever
produces the same `_apply_key`-shaped dicts main.py's browser handler and AI Operator already
consume, so a physical button press is dispatched through the identical validated path as a
browser click (see main.py's `_apply_key`).

Six categories, cycled with the joystick: left/right moves between categories, up/down moves the
selected item within a category. Joystick push or button 0 confirms/executes the selected item;
button 1 cancels back to the DIGIT category without side effects; button 2 is only meaningful in
the REGISTER category, where it splits/unsplits the currently latched register instead of
confirming it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

CAT_DIGIT = 0
CAT_OPERATOR = 1
CAT_REGISTER = 2
CAT_START = 3
CAT_CARD = 4
CAT_SYSTEM = 5

CATEGORY_NAMES = ["DIGIT", "OP", "REG", "START", "CARD", "SYS"]

DIGIT_ITEMS = list("0123456789.")

# (label shown on the Qwiic matrix, operator code sent as the "operator" key -- matches
# engine.instructions's OP_* string values).
OPERATOR_ITEMS = [
    ("+", "add"),
    ("-", "sub"),
    ("x", "mul"),
    (":", "div"),
    ("sqrt", "sqrt"),
    ("A_down", "transfer_to_m"),
    ("A_hat", "exchange_a"),
    ("decpt", "decimal_part"),
    ("clear", "clear"),
    ("print", "print"),
    ("S", "stop"),
    ("RS", "rs"),
]

REGISTER_ITEMS = ["(none)", "M", "R", "B", "C", "D", "E", "F"]
SPLITTABLE_REGISTERS = ("B", "C", "D", "E", "F")

START_ITEMS = ["V", "W", "Y", "Z"]

SYSTEM_ITEMS = ["ACK ERROR", "CLEAR TAPE", "TOGGLE RECORD"]


@dataclass
class PhysicalControl:
    """Holds joystick/button-driven cursor state and turns confirmed selections into
    `_apply_key`-shaped dicts. `card_titles` is called live (not cached) each time the CARD
    category is entered/browsed, so newly saved cards show up immediately."""

    apply_key: Callable[[dict], None]
    card_titles: Callable[[], list[str]]

    category: int = CAT_DIGIT
    item_index: int = 0
    latched_register: str | None = None
    _joy_latched_x: int = field(default=0, repr=False)
    _joy_latched_y: int = field(default=0, repr=False)

    _JOY_THRESHOLD = 40  # int8_t units (roughly a third of full deflection) before an axis "fires"

    def _items(self) -> list:
        if self.category == CAT_DIGIT:
            return DIGIT_ITEMS
        if self.category == CAT_OPERATOR:
            return OPERATOR_ITEMS
        if self.category == CAT_REGISTER:
            return REGISTER_ITEMS
        if self.category == CAT_START:
            return START_ITEMS
        if self.category == CAT_CARD:
            return self.card_titles() or ["(no cards)"]
        return SYSTEM_ITEMS

    def _clamp_item(self) -> None:
        items = self._items()
        if self.item_index >= len(items):
            self.item_index = len(items) - 1
        if self.item_index < 0:
            self.item_index = 0

    def on_joystick(self, nx: int, ny: int, push: bool) -> None:
        """nx/ny are signed, roughly in [-127, 127] (see sketch.ino's ModulinoJoystick.getX/Y).
        Edge-detected against the last-fired direction so holding the stick over doesn't repeat-
        fire every 16ms poll tick -- it must return to (roughly) center before firing again."""
        if abs(nx) < self._JOY_THRESHOLD:
            self._joy_latched_x = 0
        elif self._joy_latched_x == 0:
            self._joy_latched_x = 1 if nx > 0 else -1
            self.category = (self.category + self._joy_latched_x) % len(CATEGORY_NAMES)
            self.item_index = 0

        if abs(ny) < self._JOY_THRESHOLD:
            self._joy_latched_y = 0
        elif self._joy_latched_y == 0:
            self._joy_latched_y = 1 if ny > 0 else -1
            self.item_index += self._joy_latched_y
            self._clamp_item()

        if push:
            self._confirm()

    def on_button(self, index: int, pressed: bool) -> None:
        if not pressed:
            return
        if index == 0:
            self._confirm()
        elif index == 1:
            self.category = CAT_DIGIT
            self.item_index = 0
            self.latched_register = None
        elif index == 2 and self.category == CAT_REGISTER:
            self._toggle_split()

    def _toggle_split(self) -> None:
        items = self._items()
        reg = items[self.item_index]
        if reg not in SPLITTABLE_REGISTERS:
            return
        key = "split" if reg != self.latched_register else "unsplit"
        # Splitting doesn't change the latch -- it's an independent register-layout toggle.
        self.apply_key({key: reg})

    def _confirm(self) -> None:
        self._clamp_item()
        items = self._items()
        item = items[self.item_index]

        if self.category == CAT_DIGIT:
            self.apply_key({"digit": item})
        elif self.category == CAT_OPERATOR:
            _, op_code = item
            self.apply_key({"operator": op_code, "register": self.latched_register})
            self.latched_register = None
        elif self.category == CAT_REGISTER:
            self.latched_register = None if item == "(none)" else item
        elif self.category == CAT_START:
            self.apply_key({"start_key": item})
        elif self.category == CAT_CARD:
            if item != "(no cards)":
                self.apply_key({"load_card": {"title": item}})
        elif self.category == CAT_SYSTEM:
            if item == "ACK ERROR":
                self.apply_key({"acknowledge_error": True})
            elif item == "CLEAR TAPE":
                self.apply_key({"clear_tape": True})
            elif item == "TOGGLE RECORD":
                self.apply_key({"toggle_record": True})

    def status_text(self) -> str:
        """One-line status for the Qwiic matrix: category, selected item, and the latched
        register if any -- e.g. "OP > + (REG:B)", "CARD > Fibonacci", "DIGIT > 7"."""
        items = self._items()
        self._clamp_item()
        item = items[self.item_index]
        label = item[0] if self.category == CAT_OPERATOR else str(item)
        text = f"{CATEGORY_NAMES[self.category]} > {label}"
        if self.latched_register:
            text += f" (REG:{self.latched_register})"
        return text
