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

import socket
from typing import List


def checksum(s: str) -> int:
    sum = 0
    for c in s:
        sum += ord(c)
    return sum % 256

def escape(s: str) -> str:
    r = ""
    for c in s:
        if c == "$" or c == "#" or c == "*" or c == "}":
            r += "}" + str(ord(c) ^ 0x20)
        else:
            r += c
    return r

def decompose(s: str) -> List[str]:
    i = 0
    l = []
    b = ""
    while i < len(s):
        if s[i] == "\\" and i < len(s) - 1:
            b += s[i+1]
            i += 2
        elif s[i] == ",":
            l.append(b)
            b = ""
            i += 1
        else:
            b += s[i]
            i += 1

    l.append(b)
    return l

class Connection:
    def __init__(self, address: str):
        self.host: str = ""
        self.port: int = 0
        self.socket = None

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
                return
            except OSError as e:
                 continue

        raise OSError("Could not connect to {} on port {}".format(host, port))

    def disconnect(self):
        if not self.connected():
            return

        self.host = ""
        self.port = 0
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()

    def peer(self) -> str:
        if not self.connected():
            return "not connected"
        return self.host + ":" + str(self.port)

    def signal(self, sig: str):
        if not self.connected():
            raise Exception("not connected")
        if len(sig) > 1:
            raise Exception("invalid signal: " + sig)
        self.socket.send(sig.encode())

    def send(self, data: str):
        if not self.connected():
            raise Exception("not connected")

        data = escape(data)

        for _ in range(5):
            chk = "{0:02x}".format(checksum(data))
            pkt = "$" + data + "#" + chk
            self.socket.send(pkt.encode())
            resp = self.socket.recv(1).decode()
            if resp == '+':
                return

        raise Exception("failed to send command: " + data)

    def recv(self) -> str:
        packet = ""
        chksum = 0
        repeat = 5 # number of attempts to receive a valid response paket
        maxlen = 10000000 # response length limit

        while True:
            if not self.connected():
                raise Exception("not connected")

            r = self.socket.recv(1).decode()
            if r == "$":
                packet = ""
                chksum = 0
                continue

            if r == '#':
                chksum = chksum % 256
                refsum = int(self.socket.recv(2).decode(), 16)
                if chksum == refsum:
                    self.socket.send("+".encode())
                    return packet
                self.socket.send("-".encode())
                repeat = repeat - 1
                if repeat == 0:
                    raise Exception("failed to receive response")

            if r == "}":
                chksum += ord(r)
                r = self.socket.recv(1).decode()
                chksum += ord(r)
                packet += str(ord(r) ^ 0x20)
            else:
                chksum += ord(r)
                packet += str(r)

            if len(packet) > maxlen:
                raise Exception("response length exceeds limit")

    def command(self, cmd):
        self.send(cmd)
        raw = self.recv()
        v = decompose(raw)

        if len(v) == 0:
            raise Exception("failed to parse response: '" + raw + "'")
        if v[0] != "OK":
            raise Exception(", ".join(v[1:]))
        return v[1:]
