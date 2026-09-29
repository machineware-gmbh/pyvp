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
import socket


def checksum(s: str) -> int:
    sum = 0
    for c in s:
        sum += ord(c)
    return sum % 256


def rsp_escape(s: str) -> str:
    r = ""
    for c in s:
        if c == "$" or c == "#" or c == "*" or c == "}":
            r += "}" + str(ord(c) ^ 0x20)
        else:
            r += c
    return r


def rsp_unescape(s: str) -> str:
    if "}" not in s:
        return s
    return re.sub(r"\}(.)", lambda m: chr(ord(m[1]) ^ 0x20), s, flags=re.S)


def vsp_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,")


def decompose(s: str) -> list[str]:
    if "\\" not in s:
        return s.split(",")

    i = 0
    parts = []
    b = []
    for m in re.finditer(r"\\(.)|,", s, flags=re.S):
        b.append(s[i : m.start()])
        if m[1] is not None:
            b.append(m[1])
        else:
            parts.append("".join(b))
            b = []
        i = m.end()

    b.append(s[i:])
    parts.append("".join(b))
    return parts


class Connection:
    def __init__(self, address: str):
        self.host: str = ""
        self.port: int = 0
        self.socket: socket.socket | None = None
        self._rxbuf = bytearray()

        addr = address.rsplit(":", 1)
        if len(addr) != 2:
            raise Exception("invalid address: " + address)

        self.connect(str(addr[0]), int(addr[1]))

    def __del__(self):
        if self.connected():
            self.disconnect()

    def connected(self):
        return self.host and self.port

    def connect(self, host: str, port: int):
        if self.connected():
            self.disconnect()

        if not host:
            host = "localhost"

        for family, socktype, proto, _, addr in socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM):
            try:
                self.socket = socket.socket(family, socktype, proto)
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.socket.settimeout(5.0)
                self.socket.connect(addr)
                self.host = str(host)
                self.port = int(port)
                self._rxbuf = bytearray()
                return
            except OSError:
                continue

        raise OSError(f"Could not connect to {host} on port {port}")

    def disconnect(self):
        if not self.connected():
            return
        assert self.socket
        self.host = ""
        self.port = 0
        self.socket.close()

    def peer(self) -> str:
        if not self.connected():
            return "not connected"
        return self.host + ":" + str(self.port)

    def signal(self, sig: str):
        if not self.connected():
            raise Exception("not connected")
        assert self.socket
        if len(sig) > 1:
            raise Exception("invalid signal: " + sig)
        self.socket.send(sig.encode())

    def send(self, data: str):
        if not self.connected():
            raise Exception("not connected")
        assert self.socket

        data = rsp_escape(data)

        for _ in range(5):
            chk = f"{checksum(data):02x}"
            pkt = "$" + data + "#" + chk
            self.socket.send(pkt.encode())
            if not self._rxbuf:
                self._fill()
            resp = self._rxbuf[:1]
            del self._rxbuf[:1]
            if resp == b"+":
                return

        raise Exception("failed to send command: " + data)

    def _fill(self):
        assert self.socket
        data = self.socket.recv(1 * 1024 * 1024)
        if not data:
            raise Exception("connection closed by peer")
        self._rxbuf += data

    def recv(self) -> str:
        repeat = 5  # number of attempts to receive a valid response paket
        maxlen = 50_000_000  # response length limit
        buf = self._rxbuf

        while True:
            if not self.connected():
                raise Exception("not connected")
            assert self.socket

            # wait until we have '#' followed by two checksum digits
            pos = 0
            end = buf.find(b"#")
            while end < 0 or len(buf) < end + 3:
                if end < 0:
                    pos = len(buf)
                    if pos > 2 * maxlen:
                        raise Exception("response length exceeds limit")
                self._fill()
                if end < 0:
                    end = buf.find(b"#", pos)

            # anything before the last '$' is discarded
            start = buf.rfind(b"$", 0, end) + 1
            payload = bytes(buf[start:end])
            refsum = int(buf[end + 1 : end + 3], 16)
            del buf[: end + 3]

            if sum(payload) % 256 != refsum:
                self.socket.send(b"-")
                repeat = repeat - 1
                if repeat == 0:
                    raise Exception("failed to receive response")
                continue

            self.socket.send(b"+")
            packet = rsp_unescape(payload.decode())
            if len(packet) > maxlen:
                raise Exception("response length exceeds limit")
            return packet

    def command(self, args: list[str]) -> list[str]:
        self.send(",".join(vsp_escape(a) for a in args))
        raw = self.recv()
        v = decompose(raw)

        if len(v) == 0:
            raise Exception("failed to parse response: '" + raw + "'")
        if v[0] != "OK":
            raise Exception(", ".join(v[1:]))
        return v[1:]
