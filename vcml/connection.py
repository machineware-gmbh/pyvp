 ##############################################################################
 #                                                                            #
 # Copyright 2022 MachineWare GmbH                                            #
 # All Rights Reserved                                                        #
 #                                                                            #
 # This is unpublished proprietary work and may not be used or disclosed to   #
 # third parties, copied or duplicated in any form, in whole or in part,      #
 # without prior written permission of the authors.                           #
 #                                                                            #
 ##############################################################################

import socket
from typing import List


def checksum(s: str) -> int:
    sum = 0
    for c in s:
        sum += ord(c)
    return sum % 256

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
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.settimeout(5.0)

        addr = address.split(":")
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

        self.socket.connect((host, port))
        self.host = str(host)
        self.port = int(port)

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

        for _ in range(5):
            chk = "{0:02x}".format(checksum(data))
            pkt = "$" + data + "#" + chk
            self.socket.send(pkt.encode())
            resp = self.socket.recv(1).decode()
            if resp == '+':
                return

        raise Exception("failed to send command")

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

            if r == "\\":
                chksum += ord(r)
                r = self.socket.recv(1).decode()

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
