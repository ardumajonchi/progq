# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Register model for the Programma 101: ten registers -- M, A, R, B, C, D, E, F, p1, p2. Five of
them (B, C, D, E, F) can independently "split" into two half-capacity registers, matching the real
machine's documented behavior. Values are held as `Decimal`, since the P101's native arithmetic is
decimal (not binary float) -- this is a clean-room reimplementation from the machine's documented
register/capacity rules, not a port of any existing emulator's code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

FULL_DIGITS = 22
HALF_DIGITS = 11

SPLITTABLE = ("B", "C", "D", "E", "F")
OPERATIONAL = ("M", "A", "R")
ALL_REGISTERS = ["M", "A", "R", "B", "C", "D", "E", "F", "p1", "p2"]


class RegisterError(Exception):
    """Raised for any illegal register operation: overflow, addressing a split register as a
    whole, or splitting a register that can't be split."""


def _digit_count(value: Decimal) -> int:
    return len(value.as_tuple().digits)


def _check_capacity(value: Decimal, max_digits: int) -> None:
    digits = _digit_count(value)
    if digits > max_digits:
        raise RegisterError(f"value {value} needs {digits} digits, register only holds {max_digits}")


@dataclass
class HalfRegister:
    """One half of a split register: an independent 11-digit signed decimal slot."""

    value: Decimal = Decimal(0)

    def set(self, value: Decimal) -> None:
        _check_capacity(value, HALF_DIGITS)
        self.value = value

    def clear(self) -> None:
        self.value = Decimal(0)


@dataclass
class Register:
    """A single P101 register. Starts unsplit, holding one 22-digit `value`. `split()` converts
    it into two independent HalfRegisters (`upper`/`lower`) -- only legal for B, C, D, E, F."""

    name: str
    value: Decimal = Decimal(0)
    is_split: bool = False
    upper: HalfRegister = field(default_factory=HalfRegister)
    lower: HalfRegister = field(default_factory=HalfRegister)

    def get(self) -> Decimal:
        if self.is_split:
            raise RegisterError(f"register {self.name} is split; address .upper/.lower instead")
        return self.value

    def set(self, value: Decimal) -> None:
        if self.is_split:
            raise RegisterError(f"register {self.name} is split; address .upper/.lower instead")
        _check_capacity(value, FULL_DIGITS)
        self.value = value

    def split(self) -> None:
        if self.name not in SPLITTABLE:
            raise RegisterError(f"register {self.name} cannot be split")
        self.is_split = True
        self.upper = HalfRegister()
        self.lower = HalfRegister()

    def unsplit(self) -> None:
        self.is_split = False
        self.value = Decimal(0)

    def clear(self) -> None:
        self.value = Decimal(0)
        self.upper = HalfRegister()
        self.lower = HalfRegister()
        self.is_split = False


class RegisterFile:
    """The full bank of ten P101 registers, addressable by name."""

    def __init__(self) -> None:
        self.by_name = {name: Register(name) for name in ALL_REGISTERS}

    def __getitem__(self, name: str) -> Register:
        return self.by_name[name]

    def clear_all(self) -> None:
        for reg in self.by_name.values():
            reg.clear()

    def snapshot(self) -> dict:
        """Plain-data view for the UI: register name -> string value (or two half-values if
        split)."""
        out = {}
        for name, reg in self.by_name.items():
            if reg.is_split:
                out[name] = {"split": True, "upper": str(reg.upper.value), "lower": str(reg.lower.value)}
            else:
                out[name] = {"split": False, "value": str(reg.value)}
        return out
