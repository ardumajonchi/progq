# SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Orchestrator: wires the Programma 101 emulation core to the arduino:web_ui Brick. Unlike a
turn-based game there's no AI/turn machinery here -- every key press synchronously advances the
Machine by one step and the updated state is broadcast back to the browser.

WebUI message protocol (event "key"):
  {"digit": "7"}                        -- key a digit/decimal point into the entry buffer
  {"operator": "add", "register": "B"}  -- execute one instruction now (register is optional;
                                            omitting it uses the entry buffer as the operand)
  {"clear_entry": true}                 -- clear the typed-but-not-committed entry buffer
  {"acknowledge_error": true}           -- the S key, pressed to clear a blocked/error state
  {"split": "B"} / {"unsplit": "B"}     -- split/unsplit one of B, C, D, E, F
  {"start_key": "V"}                    -- run the loaded program from that start key's label
  {"toggle_record": true}               -- enter/leave program-recording mode
  {"mark_label": 3}                     -- while recording, mark the current step as label 3
  {"commit_program": {"title": "..."}}  -- save the recorded buffer as a card and load it
  {"load_card": {"title": "..."}}       -- load a previously saved (or demo) card as the program
  {"delete_card": {"title": "..."}}     -- delete a saved card
  {"clear_tape": true}                  -- clear the printer tape
While `record_mode` is on, "operator"/"digit" keys append to the in-progress program instead of
executing immediately (interactive/calculator mode resumes once recording stops).
"""

from __future__ import annotations

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App

from cardstore import CardStore
from engine.cards import CardError, ProgramCard, demo_countdown_card
from engine.cpu import CpuError, Machine
from engine.instructions import Instruction, START_KEYS
from engine.printer import Tape
from hw import Hardware

_DB_NAME = "cards.db"


def public_state(machine: Machine, tape: Tape, record: dict, card_titles: list[str]) -> dict:
    return {
        "registers": machine.registers.snapshot(),
        "entry": machine.entry,
        "blocked_error": machine.blocked_error,
        "tape": tape.lines[-200:],
        "record_mode": record["active"],
        "record_length": len(record["instructions"]),
        "record_labels": record["labels"],
        "card_titles": card_titles,
        "program_loaded": bool(machine.program),
    }


def main():
    machine = Machine()
    tape = Tape()
    record = {"active": False, "instructions": [], "labels": {}}

    card_store = CardStore(_DB_NAME)
    if not card_store.list_titles():
        card_store.save(demo_countdown_card())

    try:
        hw = Hardware()
        hw.play_startup()
    except Exception as exc:
        print(f"[progq] Hardware init failed, running without MCU/Bridge: {exc!r}")
        hw = None

    def buzz(kind: str) -> None:
        if hw is None:
            return
        {"click": hw.play_click, "error": hw.play_error, "print": hw.play_print_chatter}[kind]()

    ui = WebUI()

    def broadcast_state() -> None:
        ui.send_message("state", public_state(machine, tape, record, card_store.list_titles()))

    def _handle_operator(operator: str, register: str | None) -> None:
        if record["active"]:
            record["instructions"].append(Instruction(operator=operator, register=register))
            tape.echo_key(operator, register)
            return
        tape.echo_key(operator, register)
        try:
            result = machine.press_key(operator, register)
        except CpuError:
            buzz("error")
            return
        buzz("click")
        if result is not None:
            tape.print_value(result, register)
            buzz("print")

    def _handle_digit(digit: str) -> None:
        if record["active"]:
            record["instructions"].append(Instruction(operator="digit", operand=digit))
            return
        try:
            machine.key_digit(digit)
        except ValueError:
            buzz("error")
            return
        buzz("click")

    def _handle_start_key(start_key: str) -> None:
        if start_key not in START_KEYS:
            return
        try:
            printed = machine.run_from(start_key)
        except CpuError:
            buzz("error")
            return
        for value in printed:
            tape.print_value(value)
        if printed:
            buzz("print")
        else:
            buzz("click")

    def _handle_commit_program(title: str) -> None:
        try:
            card = ProgramCard(title=title, instructions=list(record["instructions"]), labels=dict(record["labels"]))
        except CardError:
            buzz("error")
            return
        card_store.save(card)
        machine.load_program(card.instructions, card.labels)
        record["active"] = False
        record["instructions"] = []
        record["labels"] = {}
        buzz("click")

    def _handle_load_card(title: str) -> None:
        card = card_store.load(title)
        if card is None:
            buzz("error")
            return
        machine.load_program(card.instructions, card.labels)
        buzz("click")

    def _on_key(sid, data):
        data = data or {}
        if "digit" in data:
            _handle_digit(str(data["digit"]))
        elif "operator" in data:
            _handle_operator(data["operator"], data.get("register"))
        elif data.get("clear_entry"):
            machine.clear_entry()
        elif data.get("acknowledge_error"):
            machine.acknowledge_error()
            buzz("click")
        elif "split" in data:
            machine.registers[data["split"]].split()
        elif "unsplit" in data:
            machine.registers[data["unsplit"]].unsplit()
        elif "start_key" in data:
            _handle_start_key(data["start_key"])
        elif "toggle_record" in data:
            record["active"] = not record["active"]
            if record["active"]:
                record["instructions"] = []
                record["labels"] = {}
        elif "mark_label" in data:
            if record["active"]:
                record["labels"][int(data["mark_label"])] = len(record["instructions"])
        elif "commit_program" in data:
            _handle_commit_program(data["commit_program"]["title"])
        elif "load_card" in data:
            _handle_load_card(data["load_card"]["title"])
        elif "delete_card" in data:
            card_store.delete(data["delete_card"]["title"])
        elif data.get("clear_tape"):
            tape.clear()

        broadcast_state()

    def _on_connect(sid):
        broadcast_state()

    ui.on_connect(_on_connect)
    ui.on_message("key", _on_key)

    ui.expose_api("GET", "/api/state", lambda: public_state(machine, tape, record, card_store.list_titles()))
    ui.expose_api("GET", "/api/tape", lambda: {"text": tape.as_text()})

    App.run()


if __name__ == "__main__":
    main()
