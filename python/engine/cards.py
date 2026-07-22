# SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Program cards: the real P101 stored programs on a magnetic card with two independently
addressable program stripes, each holding up to 120 one-byte BCD-encoded instructions (partial/
print-mode programs used a 48-instruction capacity loaded at an offset). This module models a card
as plain data (title + instruction list + label table) suitable for JSON encoding into the
dbstorage_sqlstore Brick -- a clean-room definition against the documented card capacity, not a
port of any existing emulator's on-disk format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .instructions import MAX_LABEL, OP_COND_JUMP, OP_DIGIT, OP_JUMP, Instruction

FULL_CAPACITY = 120
PARTIAL_CAPACITY = 48


class CardError(Exception):
    """Raised when a card exceeds its instruction capacity or has a malformed label table."""


@dataclass
class ProgramCard:
    """A named, saved program: its instructions plus the label -> program-index table used by
    jump/cond-jump instructions and the four start keys."""

    title: str
    instructions: list[Instruction] = field(default_factory=list)
    labels: dict[int, int] = field(default_factory=dict)
    capacity: int = FULL_CAPACITY

    def __post_init__(self) -> None:
        if self.capacity not in (FULL_CAPACITY, PARTIAL_CAPACITY):
            raise CardError(f"invalid card capacity {self.capacity}")
        self._check_capacity()
        for label in self.labels:
            if not (1 <= label <= MAX_LABEL):
                raise CardError(f"label {label} out of range 1..{MAX_LABEL}")

    def _check_capacity(self) -> None:
        if len(self.instructions) > self.capacity:
            raise CardError(
                f"program has {len(self.instructions)} instructions, card holds {self.capacity}"
            )

    def append(self, instr: Instruction) -> None:
        if len(self.instructions) >= self.capacity:
            raise CardError(f"card is full at {self.capacity} instructions")
        self.instructions.append(instr)

    def to_record(self) -> dict:
        """Plain-data form suitable for SQLStore/JSON persistence."""
        return {
            "title": self.title,
            "capacity": self.capacity,
            "labels": json.dumps({str(k): v for k, v in self.labels.items()}),
            "instructions": json.dumps(
                [
                    {"operator": i.operator, "register": i.register, "operand": i.operand}
                    for i in self.instructions
                ]
            ),
        }

    @classmethod
    def from_record(cls, record: dict) -> "ProgramCard":
        instructions = [
            Instruction(operator=item["operator"], register=item["register"], operand=item["operand"])
            for item in json.loads(record["instructions"])
        ]
        labels = {int(k): v for k, v in json.loads(record["labels"]).items()}
        return cls(
            title=record["title"],
            instructions=instructions,
            labels=labels,
            capacity=record["capacity"],
        )

    def to_text(self) -> str:
        """Human-readable plain-text card format, for the browser's card download/upload
        feature -- one instruction per line as `operator [reg=X] [operand=Y]`, preceded by a
        small header of `key: value` lines. Round-trips exactly through `from_text`."""
        lines = [
            f"title: {self.title}",
            f"capacity: {self.capacity}",
            "labels: " + ",".join(f"{label}={index}" for label, index in sorted(self.labels.items())),
            "---",
        ]
        for instr in self.instructions:
            parts = [instr.operator]
            if instr.register is not None:
                parts.append(f"reg={instr.register}")
            if instr.operand is not None:
                parts.append(f"operand={instr.operand}")
            lines.append(" ".join(parts))
        return "\n".join(lines) + "\n"

    @classmethod
    def from_text(cls, text: str) -> "ProgramCard":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = None
        capacity = FULL_CAPACITY
        labels: dict[int, int] = {}
        body_start = 0
        for i, line in enumerate(lines):
            if line == "---":
                body_start = i + 1
                break
            if line.startswith("title:"):
                title = line[len("title:") :].strip()
            elif line.startswith("capacity:"):
                capacity = int(line[len("capacity:") :].strip())
            elif line.startswith("labels:"):
                raw = line[len("labels:") :].strip()
                if raw:
                    for pair in raw.split(","):
                        label_str, index_str = pair.split("=")
                        labels[int(label_str)] = int(index_str)
            else:
                raise CardError(f"malformed card header line: {line!r}")
        if title is None:
            raise CardError("card text is missing a 'title:' header line")

        instructions = []
        for line in lines[body_start:]:
            tokens = line.split()
            operator = tokens[0]
            register = None
            operand: str | int | None = None
            for token in tokens[1:]:
                key, _, value = token.partition("=")
                if key == "reg":
                    register = value
                elif key == "operand":
                    operand = int(value) if operator in (OP_JUMP, OP_COND_JUMP) else value
                else:
                    raise CardError(f"malformed instruction line: {line!r}")
            if operator == OP_DIGIT and operand is not None:
                operand = str(operand)
            instructions.append(Instruction(operator=operator, register=register, operand=operand))

        return cls(title=title, instructions=instructions, labels=labels, capacity=capacity)


def demo_countdown_card() -> ProgramCard:
    """The bundled demo, matching EMU101's own: "Press V, 10, S" -- a simple countdown-by-one
    loop from an operator-entered starting value down to zero, printing each step."""
    from .instructions import OP_PRINT, OP_STOP, OP_SUB

    instructions = [
        Instruction(operator=OP_PRINT, register="A"),
        Instruction(operator=OP_SUB, register="M"),
        Instruction(operator=OP_COND_JUMP, operand=2),
        Instruction(operator=OP_JUMP, operand=1),
        Instruction(operator=OP_STOP),
    ]
    labels = {1: 0, 2: 4}
    return ProgramCard(title="Countdown demo", instructions=instructions, labels=labels)


def fibonacci_card() -> ProgramCard:
    """Prints the first 10 Fibonacci terms. Setup: select F, clear, type 9, add with no
    register, exchange with A (F holds the term counter); select B, clear, type 1, add with no
    register (A=1, B=0 are the first two terms). Uses C/D as exchange scratch and M as a
    counter-swap staging register since every arithmetic op always targets A."""
    from .instructions import (
        OP_ADD,
        OP_CLEAR,
        OP_COND_JUMP,
        OP_DIGIT,
        OP_EXCHANGE_A,
        OP_JUMP,
        OP_PRINT,
        OP_STOP,
        OP_SUB,
    )

    loop_body = [
        Instruction(operator=OP_PRINT, register="A"),
        Instruction(operator=OP_CLEAR, register="C"),
        Instruction(operator=OP_CLEAR, register="D"),
        Instruction(operator=OP_EXCHANGE_A, register="C"),
        Instruction(operator=OP_ADD, register="B"),
        Instruction(operator=OP_ADD, register="C"),
        Instruction(operator=OP_EXCHANGE_A, register="D"),
        Instruction(operator=OP_EXCHANGE_A, register="C"),
        Instruction(operator=OP_EXCHANGE_A, register="B"),
        Instruction(operator=OP_EXCHANGE_A, register="D"),
        Instruction(operator=OP_EXCHANGE_A, register="M"),
        Instruction(operator=OP_EXCHANGE_A, register="F"),
        Instruction(operator=OP_DIGIT, operand="1"),
        Instruction(operator=OP_SUB),
        Instruction(operator=OP_EXCHANGE_A, register="F"),
        Instruction(operator=OP_EXCHANGE_A, register="M"),
        Instruction(operator=OP_COND_JUMP, operand=2),
        Instruction(operator=OP_JUMP, operand=1),
    ]
    instructions = loop_body + [Instruction(operator=OP_STOP)]
    labels = {1: 0, 2: len(loop_body)}
    return ProgramCard(title="Fibonacci sequence", instructions=instructions, labels=labels)


def compound_interest_card() -> ProgramCard:
    """Prints an investment's balance after each year of compounding. Setup: select F, clear,
    type (years-1), add with no register, exchange with A (F holds the year counter); select M,
    clear, type the growth factor e.g. 1.05 for 5%, add with no register, exchange with A; type
    the principal, add with no register into A."""
    from .instructions import (
        OP_ADD,
        OP_CLEAR,
        OP_COND_JUMP,
        OP_DIGIT,
        OP_EXCHANGE_A,
        OP_JUMP,
        OP_MUL,
        OP_PRINT,
        OP_STOP,
        OP_SUB,
    )

    loop_body = [
        Instruction(operator=OP_MUL, register="M"),
        Instruction(operator=OP_PRINT, register="A"),
        Instruction(operator=OP_EXCHANGE_A, register="C"),
        Instruction(operator=OP_EXCHANGE_A, register="F"),
        Instruction(operator=OP_DIGIT, operand="1"),
        Instruction(operator=OP_SUB),
        Instruction(operator=OP_EXCHANGE_A, register="F"),
        Instruction(operator=OP_EXCHANGE_A, register="C"),
        Instruction(operator=OP_COND_JUMP, operand=2),
        Instruction(operator=OP_JUMP, operand=1),
    ]
    instructions = loop_body + [Instruction(operator=OP_STOP)]
    labels = {1: 0, 2: len(loop_body)}
    return ProgramCard(title="Compound interest", instructions=instructions, labels=labels)


def pythagorean_card() -> ProgramCard:
    """Prints the hypotenuse c = sqrt(a^2 + b^2). Setup: type side b, add with no register
    into A, exchange with B (B now holds side b, A is cleared); type side a, add with no
    register into A."""
    from .instructions import OP_ADD, OP_EXCHANGE_A, OP_MUL, OP_PRINT, OP_SQRT, OP_STOP

    instructions = [
        Instruction(operator=OP_MUL, register="A"),
        Instruction(operator=OP_EXCHANGE_A, register="C"),
        Instruction(operator=OP_ADD, register="B"),
        Instruction(operator=OP_MUL, register="B"),
        Instruction(operator=OP_ADD, register="C"),
        Instruction(operator=OP_SQRT),
        Instruction(operator=OP_PRINT),
        Instruction(operator=OP_STOP),
    ]
    return ProgramCard(title="Pythagorean theorem", instructions=instructions, labels={1: 0})


def moon_landing_card() -> ProgramCard:
    """Prints the impact velocity v = sqrt(2*g*h) of a free-falling object under lunar gravity
    (g=1.62 m/s^2) -- the class of descent-trajectory calculation that made the Programma 101
    famous when NASA engineers used one to help verify Apollo 11's lunar module descent. Setup:
    clear, type 2, add with no register, exchange with B; type 1.62, add with no register,
    exchange with M; type the drop height h in meters, add with no register into A."""
    from .instructions import OP_EXCHANGE_A, OP_MUL, OP_PRINT, OP_SQRT, OP_STOP

    instructions = [
        Instruction(operator=OP_MUL, register="M"),
        Instruction(operator=OP_MUL, register="B"),
        Instruction(operator=OP_SQRT),
        Instruction(operator=OP_PRINT),
        Instruction(operator=OP_STOP),
    ]
    return ProgramCard(title="Moon landing descent velocity", instructions=instructions, labels={1: 0})
