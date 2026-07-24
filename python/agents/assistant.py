# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Assistant agent: plain-chat explanations on the official arduino:llm Brick, for two on-screen
"?" buttons -- explain a blocked error in plain English, and narrate what a loaded program card
does. Purely explanatory: never mutates machine/tape/card state, only reads it."""

from __future__ import annotations

from arduino.app_bricks.llm import LargeLanguageModel

_SYSTEM_PROMPT = (
    "You explain the Olivetti Programma 101, a 1965 programmable desktop calculator, to someone "
    "using an on-screen emulator of it. Be concise (2-4 sentences), plain-English, and concrete -- "
    "reference the actual register values and instructions you're given rather than speaking "
    "generically. Never invent instructions or values not present in what you're shown."
)


class Assistant:
    def __init__(self, model: str | None = None):
        self.llm = LargeLanguageModel(system_prompt=_SYSTEM_PROMPT, max_tokens=220, model=model)

    def explain_error(self, error: str, registers: dict, entry: str) -> str:
        prompt = (
            f"The machine is blocked with error: {error!r}\n"
            f"Register snapshot: {registers}\n"
            f"Typed-but-not-committed entry buffer: {entry!r}\n\n"
            "Explain in plain English why this happened and what the operator should try next "
            "(remember: pressing S clears the error)."
        )
        return self.llm.chat(prompt).strip()

    def explain_card(self, title: str, instructions: list[dict], labels: dict) -> str:
        steps = "\n".join(
            f"{i}. {instr['operator']}"
            + (f" reg={instr['register']}" if instr.get("register") else "")
            + (f" operand={instr['operand']}" if instr.get("operand") is not None else "")
            for i, instr in enumerate(instructions)
        )
        prompt = (
            f"Card {title!r}, start labels {labels}:\n{steps}\n\n"
            "Explain step-by-step what this program computes and how, for someone about to run it."
        )
        return self.llm.chat(prompt).strip()
