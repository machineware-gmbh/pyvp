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

from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Union


def format_time(time_ps: int) -> str:
    ns = time_ps // 1000
    return f"{ns // 1_000_000_000}.{ns % 1_000_000_000:09d}s"


@dataclass
class TraceInfo:
    port: Any
    time_ps: int
    delta: int
    dir: str
    error: bool

    def is_request(self) -> bool:
        return self.dir == "fw"

    def is_response(self) -> bool:
        return self.dir == "bw"

    def __str__(self) -> str:
        err = " ERROR" if self.error else ""
        arrow = ">>" if self.is_request() else "<<"
        return f"{format_time(self.time_ps)} {self.port.hierarchy_name()} {arrow}{err}"


def _hex(data: bytes) -> str:
    return "[" + " ".join(f"{b:02x}" for b in data) + "]"


@dataclass
class TraceTlmSbi:
    is_debug: bool
    is_nodmi: bool
    is_sync: bool
    is_insn: bool
    is_excl: bool
    is_lock: bool
    is_secure: bool
    atype: str
    cpuid: int
    privilege: int
    asid: int


@dataclass
class TraceTlm:
    PROTOCOL: ClassVar[str] = "TLM"
    command: str
    address: int
    data: bytes
    byte_enable: bytes
    streaming_width: int
    dmi_allowed: bool
    response: str
    sbi: TraceTlmSbi | None = None

    def is_read(self) -> bool:
        return self.command == "READ"

    def is_write(self) -> bool:
        return self.command == "WRITE"

    def __str__(self) -> str:
        return f"TLM {self.command} @0x{self.address:x} {_hex(self.data)} {self.response}"


@dataclass
class TraceGpio:
    PROTOCOL: ClassVar[str] = "GPIO"
    state: bool
    vector: int | None = None

    def __str__(self) -> str:
        vector = f" vector={self.vector}" if self.vector is not None else ""
        return f"GPIO {int(self.state)}{vector}"


@dataclass
class TraceClk:
    PROTOCOL: ClassVar[str] = "CLK"
    period_ns: float
    posedge: bool
    duty_cycle: float

    def __str__(self) -> str:
        if self.period_ns == 0:
            return "CLK off"
        edge = "posedge" if self.posedge else "negedge"
        return f"CLK {self.period_ns:g}ns {edge} duty={self.duty_cycle:g}"


@dataclass
class TracePci:
    PROTOCOL: ClassVar[str] = "PCI"
    command: str
    response: str
    address_space: str
    address: int
    data: bytes
    debug: bool

    def __str__(self) -> str:
        return f"PCI {self.command} {self.address_space} @0x{self.address:x} {_hex(self.data)} {self.response}"


@dataclass
class TraceI2c:
    PROTOCOL: ClassVar[str] = "I2C"
    command: str
    response: str
    data: int

    def __str__(self) -> str:
        return f"I2C {self.command} 0x{self.data:02x} {self.response}"


@dataclass
class TraceLin:
    PROTOCOL: ClassVar[str] = "LIN"
    linid: int
    data: bytes
    status: str

    def __str__(self) -> str:
        return f"LIN id={self.linid} {_hex(self.data)} {self.status}"


@dataclass
class TraceSpi:
    PROTOCOL: ClassVar[str] = "SPI"
    mosi: int
    miso: int

    def __str__(self) -> str:
        return f"SPI mosi=0x{self.mosi:02x} miso=0x{self.miso:02x}"


@dataclass
class TraceSd:
    PROTOCOL: ClassVar[str] = "SD"
    command: str
    data: bytes
    status: str
    opcode: str = ""
    argument: int = 0
    crc: int = 0
    spi: bool = False

    def __str__(self) -> str:
        cmd = f" {self.opcode} arg=0x{self.argument:08x}" if self.opcode else ""
        return f"SD {self.command}{cmd} {_hex(self.data)} {self.status}"


@dataclass
class TraceVirtioBuffer:
    addr: int
    size: int


@dataclass
class TraceVirtio:
    PROTOCOL: ClassVar[str] = "VIRTIO"
    index: int
    input_buffers: list[TraceVirtioBuffer]
    output_buffers: list[TraceVirtioBuffer]
    status: str

    def __str__(self) -> str:
        def bufs(b: list[TraceVirtioBuffer]) -> str:
            return "[" + " ".join(f"0x{x.addr:x}:{x.size}" for x in b) + "]"

        return f"VIRTIO index={self.index} in={bufs(self.input_buffers)} out={bufs(self.output_buffers)} {self.status}"


@dataclass
class TraceSerial:
    PROTOCOL: ClassVar[str] = "SERIAL"
    data: int
    bits: int
    baud: int
    parity: str
    stop: str

    def __str__(self) -> str:
        c = f" '{chr(self.data)}'" if 0x20 <= self.data < 0x7F else ""
        return f"SERIAL 0x{self.data:02x}{c} {self.bits}{self.parity}{self.stop} @{self.baud}"


@dataclass
class TraceSignal:
    PROTOCOL: ClassVar[str] = "SIGNAL"
    data: bool | int | float | str | None

    def __str__(self) -> str:
        return f"SIGNAL {'null' if self.data is None else self.data}"


@dataclass
class TraceEthernet:
    PROTOCOL: ClassVar[str] = "ETHERNET"
    type: str
    source: str = ""
    destination: str = ""
    data: bytes = b""

    def __str__(self) -> str:
        addr = f" {self.source} -> {self.destination}" if self.source else ""
        return f"ETHERNET {self.type}{addr} {len(self.data)} bytes"


@dataclass
class TraceCan:
    PROTOCOL: ClassVar[str] = "CAN"
    type: str
    id: int
    xlf: bool
    fdf: bool
    eff: bool
    data: bytes
    sec: bool = False
    rrs: bool = False
    vcid: int = 0
    sdt: int = 0
    af: int = 0
    brs: bool = False
    esi: bool = False
    rtr: bool = False
    err: bool = False

    def __str__(self) -> str:
        return f"{self.type} id=0x{self.id:x} {_hex(self.data)}"


@dataclass
class TraceUsb:
    PROTOCOL: ClassVar[str] = "USB"
    token: str
    addr: int
    endpoint: int
    data: bytes
    status: str

    def __str__(self) -> str:
        return f"USB {self.token} addr={self.addr} ep={self.endpoint} {_hex(self.data)} {self.status}"


@dataclass
class TraceUnknown:
    PROTOCOL: ClassVar[str] = "UNKNOWN"
    name: str

    def __str__(self) -> str:
        return self.name


TracePayload = Union[
    TraceTlm,
    TraceGpio,
    TraceClk,
    TracePci,
    TraceI2c,
    TraceLin,
    TraceSpi,
    TraceSd,
    TraceVirtio,
    TraceSerial,
    TraceSignal,
    TraceEthernet,
    TraceCan,
    TraceUsb,
    TraceUnknown,
]

TRACE_PAYLOADS: tuple[type, ...] = (
    TraceTlm,
    TraceGpio,
    TraceClk,
    TracePci,
    TraceI2c,
    TraceLin,
    TraceSpi,
    TraceSd,
    TraceVirtio,
    TraceSerial,
    TraceSignal,
    TraceEthernet,
    TraceCan,
    TraceUsb,
    TraceUnknown,
)

TraceHandler = Callable[[TraceInfo, Any], None]


def format_trace(info: TraceInfo, tx: Any) -> str:
    return f"{info} {tx}"


@dataclass
class LedEvent:
    leds: Any
    time_ps: int
    delta: int
    index: int
    state: bool


@dataclass
class UartEvent:
    terminal: Any
    time_ps: int
    delta: int
    data: bytes = field(default=b"")


LedHandler = Callable[[LedEvent], None]
UartHandler = Callable[[UartEvent], None]


class _Mismatch(Exception):
    pass


def _get(obj: dict, key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in obj:
        raise _Mismatch(key)
    v = obj[key]
    # bool is an int in python, but never a valid number here
    if isinstance(v, bool) and kind is not bool:
        raise _Mismatch(key)
    if not isinstance(v, kind):
        raise _Mismatch(key)
    return v


def _int(obj: dict, key: str) -> int:
    return _get(obj, key, int)


def _num(obj: dict, key: str) -> float:
    return _get(obj, key, (int, float))


def _bool(obj: dict, key: str) -> bool:
    return _get(obj, key, bool)


def _str(obj: dict, key: str) -> str:
    return _get(obj, key, str)


def _bytes(obj: dict, key: str) -> bytes:
    v = _get(obj, key, list)
    if not all(isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 0xFF for b in v):
        raise _Mismatch(key)
    return bytes(v)


def _opt(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except _Mismatch:
        return default


def _buffers(obj: dict, key: str) -> list[TraceVirtioBuffer]:
    res = []
    for b in _get(obj, key, list):
        if not isinstance(b, dict):
            raise _Mismatch(key)
        res.append(TraceVirtioBuffer(_int(b, "addr"), _int(b, "size")))
    return res


def _parse(protocol: str, tx: dict) -> Any:
    if protocol == "TLM":
        sbi = None
        if "sbi" in tx:
            s = _get(tx, "sbi", dict)
            sbi = TraceTlmSbi(
                _bool(s, "is_debug"),
                _bool(s, "is_nodmi"),
                _bool(s, "is_sync"),
                _bool(s, "is_insn"),
                _bool(s, "is_excl"),
                _bool(s, "is_lock"),
                _bool(s, "is_secure"),
                _str(s, "atype"),
                _int(s, "cpuid"),
                _int(s, "privilege"),
                _int(s, "asid"),
            )
        return TraceTlm(
            _str(tx, "command"),
            _int(tx, "address"),
            _bytes(tx, "data"),
            _bytes(tx, "byte_enable"),
            _int(tx, "streaming_width"),
            _bool(tx, "dmi_allowed"),
            _str(tx, "response_status"),
            sbi,
        )

    if protocol == "GPIO":
        return TraceGpio(_bool(tx, "state"), _opt(lambda: _int(tx, "vector")))

    if protocol == "CLK":
        return TraceClk(_num(tx, "period"), _str(tx, "polarity") == "posedge", _num(tx, "duty_cycle"))

    if protocol == "PCI":
        return TracePci(
            _str(tx, "command"),
            _str(tx, "response"),
            _str(tx, "address_space"),
            _int(tx, "address"),
            _bytes(tx, "data"),
            _bool(tx, "debug"),
        )

    if protocol == "I2C":
        return TraceI2c(_str(tx, "command"), _str(tx, "response"), _int(tx, "data"))

    if protocol == "LIN":
        return TraceLin(_int(tx, "linid"), _bytes(tx, "data"), _str(tx, "status"))

    if protocol == "SPI":
        return TraceSpi(_int(tx, "mosi"), _int(tx, "miso"))

    if protocol == "SD":
        command = _str(tx, "command")
        if command in ("SD_CMD", "SD_APP_CMD"):
            return TraceSd(
                command,
                _bytes(tx, "response"),
                _str(tx, "status"),
                _str(tx, "opcode"),
                _int(tx, "argument"),
                _int(tx, "crc"),
                _bool(tx, "spi"),
            )
        # failed data reads carry no data byte
        data = _opt(lambda: _int(tx, "data"))
        return TraceSd(command, b"" if data is None else bytes([data]), _opt(lambda: _str(tx, "status"), ""))

    if protocol == "VIRTIO":
        return TraceVirtio(
            _int(tx, "index"),
            _buffers(tx, "input_buffers"),
            _buffers(tx, "output_buffers"),
            _str(tx, "status"),
        )

    if protocol == "SERIAL":
        return TraceSerial(_int(tx, "data"), _int(tx, "bits"), _int(tx, "baud"), _str(tx, "parity"), _str(tx, "stop"))

    if protocol == "SIGNAL":
        if "data" not in tx or isinstance(tx["data"], (dict, list)):
            raise _Mismatch("data")
        return TraceSignal(tx["data"])

    if protocol == "ETHERNET":
        return TraceEthernet(
            _str(tx, "type"),
            _opt(lambda: _str(tx, "sourceaddr"), ""),
            _opt(lambda: _str(tx, "destaddr"), ""),
            _opt(lambda: _bytes(tx, "data"), b""),
        )

    if protocol == "CAN":

        def flag(key: str) -> bool:
            return _opt(lambda: _bool(tx, key), False)

        def val(key: str) -> int:
            return _opt(lambda: _int(tx, key), 0)

        return TraceCan(
            _str(tx, "type"),
            _int(tx, "id"),
            _bool(tx, "xlf"),
            _bool(tx, "fdf"),
            _bool(tx, "eff"),
            _bytes(tx, "data"),
            flag("sec"),
            flag("rrs"),
            val("vcid"),
            val("sdt"),
            val("af"),
            flag("brs"),
            flag("esi"),
            flag("rtr"),
            flag("err"),
        )

    if protocol == "USB":
        return TraceUsb(_str(tx, "token"), _int(tx, "addr"), _int(tx, "endpoint"), _bytes(tx, "data"), _str(tx, "status"))

    return TraceUnknown(protocol)


def parse_payload(protocol: str, tx: Any) -> Any:
    if not isinstance(tx, dict):
        return None
    try:
        return _parse(protocol, tx)
    except _Mismatch:
        return None


def parse_uart(payload: Any) -> int | None:
    if not isinstance(payload, str) or len(payload) != 1 or ord(payload) > 0xFF:
        return None
    return ord(payload)
