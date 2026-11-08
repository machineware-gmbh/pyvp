##############################################################################
#                                                                            #
# Copyright 2024 MachineWare GmbH                                            #
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

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MemStatus(Enum):
    OK = 0  # read
    FAULT = 1  # virtual address does not translate
    BUS_ERROR = 2  # translates, but nothing responded at its address


@dataclass
class Symbol:
    name: str
    is_function: bool  # else an object, i.e. data
    addr: int
    size: int  # 0 if unknown


@dataclass
class Instruction:
    virt: int
    phys: Optional[int]  # None if it does not translate
    data: bytes
    symbol: str  # empty if none
    offset: int  # into symbol
    code: str


@dataclass
class StackFrame:
    pc: int
    fp: int  # 0 if unknown
    symbol: str  # empty if none
    offset: int  # into symbol


@dataclass
class TargetInfo:
    id: int
    pc: int
    lr: int
    sp: int
    fp: int


# "O 0x0000000080001234 name", as printed by the lsym module command
_LSYM_LINE = re.compile(r"^([FO]) (0x[0-9a-fA-F]+) (.+)$")

# "   [main+0x0004] 00000044 00000044: [13 05 00 00]    li a0, 0", as printed by
# the disas module command; ">" marks the pc, phys may be "????..."
_DISAS_LINE = re.compile(
    r"^\s*>?\s*(?:\[(.+?)\+0x([0-9a-fA-F]+)\]\s+)?([0-9a-fA-F]+)(?:\s*([0-9a-fA-F]+|\?+))?: \[([0-9a-fA-F ]*)\]\s*(.*)$"
)

# "[0x0000000000000044] main +0x4/0x20", as printed by the stack module command;
# it does not print frame pointers
_STACK_LINE = re.compile(r"^\[0x([0-9a-fA-F]+)\](?: (.+) \+0x([0-9a-fA-F]+)(?:/0x[0-9a-fA-F]+)?)?\s*$")


def _hex(s: Optional[str]) -> int:
    return int(s, 16) if s else 0


def _records(resp: list[str], n: int) -> list[list[str]]:
    if resp[0] != "OK":
        raise Exception(", ".join(resp[1:]))
    if (len(resp) - 1) % n != 0:
        raise Exception("malformed response")
    return [resp[i : i + n] for i in range(1, len(resp), n)]


class Target:
    def __init__(self, conn, xmlnode):
        self._conn = conn
        self.name = xmlnode.text

    def __str__(self):
        return self.name

    def read_vmem(self, vaddr: int, size: int) -> bytes:
        resp = self._conn.command(["vread", self.name, str(vaddr), str(size)])
        if len(resp) != size:
            raise Exception("malformed response")
        return bytes(int(b, 16) for b in resp)

    # like read_vmem, but also reports what became of each byte; bytes that
    # could not be read are zero. Simulators that cannot tell report every
    # byte as read.
    def read_vmem_ex(self, vaddr: int, size: int) -> tuple[bytes, list[MemStatus]]:
        resp = self._conn.command(["vread", self.name, str(vaddr), str(size), "status"])
        if len(resp) != size:
            raise Exception("malformed response")

        data = bytearray(size)
        status = [MemStatus.OK] * size
        for i, tok in enumerate(resp):
            if tok == "--":
                status[i] = MemStatus.FAULT
            elif tok == "**":
                status[i] = MemStatus.BUS_ERROR
            else:  # old servers ignore status and answer 0x..
                data[i] = int(tok, 16)
        return bytes(data), status

    # the symbols the target knows, e.g. from its program's ELF file; sizes
    # are 0 if the simulator does not report them
    def symbols(self) -> list[Symbol]:
        resp = self._conn.request(["lsym", self.name])

        # servers without lsym answer empty: fall back to the module command
        if resp == [""]:
            matches = (_LSYM_LINE.match(line) for line in self._exec_lines("lsym"))
            return [Symbol(m[3], m[1] == "F", int(m[2], 16), 0) for m in matches if m]

        return [Symbol(name, kind == "F", int(addr, 16), int(size)) for kind, addr, size, name in _records(resp, 4)]

    # up to count instructions from vaddr, fewer if the disassembler stops
    def disassemble(self, vaddr: int, count: int) -> list[Instruction]:
        resp = self._conn.request(["disas", self.name, str(vaddr), str(count)])

        if resp == [""]:
            # the module command takes a range: 16 bytes per instruction suffice
            lines = self._exec_lines("disas", str(vaddr), str(vaddr + count * 16))
            insns = []
            for m in (_DISAS_LINE.match(line) for line in lines):
                if not m or len(insns) >= count:
                    continue
                virt = int(m[3], 16)
                phys = virt if not m[4] else None if m[4][0] == "?" else int(m[4], 16)
                data = bytes(int(b, 16) for b in m[5].split())
                insns.append(Instruction(virt, phys, data, m[1] or "", _hex(m[2]), m[6]))
            return insns

        return [
            Instruction(_hex(virt), _hex(phys) if phys else None, bytes.fromhex(data), sym, _hex(off), code)
            for virt, phys, data, sym, off, code in _records(resp, 6)
        ]

    # innermost frame first
    def stacktrace(self, limit: int = 64) -> list[StackFrame]:
        resp = self._conn.request(["stack", self.name, str(limit)])

        if resp == [""]:
            matches = (_STACK_LINE.match(line) for line in self._exec_lines("stack"))
            return [StackFrame(int(m[1], 16), 0, m[2] or "", _hex(m[3])) for m in matches if m][:limit]

        return [StackFrame(_hex(pc), _hex(fp), sym, _hex(off)) for pc, fp, sym, off in _records(resp, 4)]

    def info(self) -> TargetInfo:
        resp = self._conn.command(["tinfo", self.name])
        vals = dict(tok.split(":", 1) for tok in resp if ":" in tok)
        return TargetInfo(*(_hex(vals.get(k)) for k in ("id", "pc", "lr", "sp", "fp")))

    def _exec_lines(self, *args: str) -> list[str]:
        out = self._conn.command(["exec", self.name, *args])
        return out[0].splitlines() if out else []
