##############################################################################
#                                                                            #
# Copyright 2026 MachineWare GmbH                                            #
#                                                                            #
# Licensed under the Apache License, Version 2.0 (the "License");            #
# you may not use this file except in compliance with the License.           #
# You may obtain a copy of the License at                                    #
#                                                                            #
#     http://www.apache.org/licenses/LICENSE-2.0                             #
#                                                                            #
# Unless required by applicable law or agreed to in writing, software        #
# distributed under the License is distributed on an "AS IS" BASIS,          #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.   #
# See the License for the specific language governing permissions and        #
# limitations under the License.                                             #
#                                                                            #
##############################################################################

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from .connection import Connection, decompose, vsp_escape
from .events import (
    TRACE_PAYLOADS,
    LedEvent,
    LedHandler,
    TraceHandler,
    TraceInfo,
    UartEvent,
    UartHandler,
    parse_payload,
    parse_uart,
)

_KNOWN_PROTOCOLS = {p.PROTOCOL for p in TRACE_PAYLOADS}


@dataclass
class _Handlers:
    led: LedHandler | None = None
    uart: UartHandler | None = None
    trace_all: TraceHandler | None = None
    trace: dict[str, TraceHandler] = field(default_factory=dict)

    def empty(self) -> bool:
        return not self.led and not self.uart and not self.trace_all and not self.trace

    def copy(self) -> _Handlers:
        return _Handlers(self.led, self.uart, self.trace_all, dict(self.trace))


class Dispatcher:
    def __init__(self, conn: Connection):
        self._conn = conn
        self._modules: dict[str, Any] = {}
        self._handlers: dict[tuple[Any, str], _Handlers] = {}
        self._publishers: dict[str, dict[Any, int]] = {}
        self._on_dropped: Callable[[int], None] | None = None
        self._dropped = 0
        self._warned: set[str] = set()

    def set_modules(self, modules: dict[str, Any]):
        self._modules = modules

    def dropped(self) -> int:
        return self._dropped

    def on_dropped(self, fn: Callable[[int], None] | None):
        self._on_dropped = fn

    def is_subscribed(self, mod: Any, event: str) -> bool:
        return (mod, event) in self._handlers

    def on_led(self, mod: Any, fn: LedHandler | None):
        def change(hs: _Handlers):
            hs.led = fn

        self._update(mod, "led", change)

    def on_uart(self, mod: Any, fn: UartHandler | None):
        def change(hs: _Handlers):
            hs.uart = fn

        self._update(mod, "uart", change)

    def on_trace(self, mod: Any, fn: TraceHandler | None, protocol: str | None = None):
        def change(hs: _Handlers):
            if protocol is None:
                hs.trace_all = fn
            elif fn:
                hs.trace[protocol] = fn
            else:
                hs.trace.pop(protocol, None)

        self._update(mod, "trace", change)

    def _command(self, args: list[str]):
        if not self._conn.connected():
            raise Exception("not connected")

        self._conn.send(",".join(vsp_escape(a) for a in args))
        resp = decompose(self._conn.recv())

        # older simulators send an empty response to unknown commands
        if resp == [""]:
            raise Exception("events not supported by simulator")
        if resp[0] != "OK":
            raise Exception(", ".join(resp[1:]))

    def _find_publishers(self, mod: Any, event: str, pubs: list[Any]) -> list[Any]:
        if event in mod.events:
            pubs.append(mod)
        for child in mod.modules:
            self._find_publishers(child, event, pubs)
        return pubs

    def _subscribe(self, mod: Any, event: str):
        pubs = self._find_publishers(mod, event, [])
        if not pubs:
            raise Exception(f"'{mod.hierarchy_name()}' does not publish '{event}' events")

        counts = self._publishers.setdefault(event, {})
        added = [p for p in pubs if not counts.get(p)]
        if added:
            self._command(["sub", event, *(p.hierarchy_name() for p in added)])

        for p in pubs:
            counts[p] = counts.get(p, 0) + 1

    def _unsubscribe(self, mod: Any, event: str):
        pubs = self._find_publishers(mod, event, [])

        counts = self._publishers.setdefault(event, {})
        removed = [p for p in pubs if counts.get(p) == 1]
        if removed:
            self._command(["unsub", event, *(p.hierarchy_name() for p in removed)])

        for p in pubs:
            n = counts.get(p, 0) - 1
            if n > 0:
                counts[p] = n
            else:
                counts.pop(p, None)

    def _update(self, mod: Any, event: str, change: Callable[[_Handlers], None]):
        key = (mod, event)
        current = self._handlers.get(key)
        hs = current.copy() if current else _Handlers()
        change(hs)

        if not current and not hs.empty():
            self._subscribe(mod, event)
        elif current and hs.empty():
            self._unsubscribe(mod, event)

        if hs.empty():
            self._handlers.pop(key, None)
        else:
            self._handlers[key] = hs

    def _collect(self, sender: Any, event: str) -> list[_Handlers]:
        found = []
        mod = sender
        while mod is not None:
            hs = self._handlers.get((mod, event))
            if hs:
                found.append(hs)
            mod = mod.parent
        return found

    def dispatch(self, text: str):
        try:
            obj = json.loads(text)
        except ValueError:
            return
        if not isinstance(obj, dict):
            return

        dropped = obj.get("dropped")
        if isinstance(dropped, int) and not isinstance(dropped, bool):
            self._dropped += dropped
            if self._on_dropped:
                self._on_dropped(dropped)

        events = obj.get("events")
        if not isinstance(events, list):
            return

        uart: UartEvent | None = None
        data = bytearray()

        def flush_uart():
            nonlocal uart
            if uart is None:
                return
            uart.data = bytes(data)
            for hs in self._collect(uart.terminal, "uart"):
                if hs.uart:
                    hs.uart(uart)
            uart = None
            data.clear()

        for entry in events:
            if not isinstance(entry, dict):
                continue
            event = entry.get("event")
            sender = entry.get("sender")
            time = entry.get("time")
            delta = entry.get("delta")
            if not isinstance(event, str) or not isinstance(sender, str):
                continue
            if not isinstance(time, int) or not isinstance(delta, int) or "payload" not in entry:
                continue
            payload = entry["payload"]

            mod = self._modules.get(sender)
            if mod is None:
                if sender not in self._warned:
                    self._warned.add(sender)
                    print(f"ignoring events of unknown object '{sender}'", file=sys.stderr)
                continue

            if event == "uart":
                byte = parse_uart(payload)
                if byte is None:
                    continue
                if uart is not None and uart.terminal is not mod:
                    flush_uart()
                if uart is None:
                    uart = UartEvent(mod, time, delta)
                data.append(byte)
                continue

            flush_uart()

            found = self._collect(mod, event)
            if not found:
                continue

            if event == "led":
                self._notify_led(found, mod, time, delta, payload)
            elif event == "trace":
                self._notify_trace(found, mod, time, delta, payload)

        flush_uart()

    def _notify_led(self, found: list[_Handlers], sender: Any, time: int, delta: int, payload: Any):
        if not isinstance(payload, dict):
            return
        index = payload.get("led")
        state = payload.get("state")
        if not isinstance(state, bool) or not isinstance(index, int) or isinstance(index, bool):
            return

        ev = LedEvent(sender, time, delta, index, state)
        for hs in found:
            if hs.led:
                hs.led(ev)

    def _notify_trace(self, found: list[_Handlers], sender: Any, time: int, delta: int, payload: Any):
        if not isinstance(payload, dict) or "tx" not in payload:
            return
        direction = payload.get("dir")
        name = payload.get("protocol")
        if not isinstance(direction, str) or not isinstance(name, str):
            return

        protocol = name if name in _KNOWN_PROTOCOLS else "UNKNOWN"

        if not any(hs.trace_all or protocol in hs.trace for hs in found):
            return
        tx = parse_payload(name, payload["tx"])
        if tx is None:
            return

        info = TraceInfo(sender, time, delta, "bw" if direction == "bw" else "fw", payload.get("error") is True)
        for hs in found:
            if hs.trace_all:
                hs.trace_all(info, tx)
            fn = hs.trace.get(protocol)
            if fn:
                fn(info, tx)
