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

from operator import truediv
import time
import threading
import xml.etree.ElementTree as ElementTree
from typing import List

from .connection import Connection
from .attribute import Attribute
from .module import Module
from .target import Target


class Session:
    def __init__(self, address: str):
        self._version: List[str] = ["unknown", "unknown"]
        self._running: bool = False
        self._reason: str = ""
        self._time: int = 0
        self._cycle: int = 0
        self._quantum: int = 0

        self._conn = Connection(address)
        self.modules = []
        self.targets = []

        self._conn.command("stop")

        self.update_version()
        self.update_quantum()
        self.update_status()
        self.update_modules()

    def __del__(self):
        if self._conn:
            self._conn.disconnect()
            self.disconnect()

    def __str__(self):
        return self.peer()

    def peer(self):
        return self._conn.peer()

    def update_version(self):
        res = self._conn.command("version")
        if len(res) != 2:
            raise Exception("unexpected response to version command: " + str(res))

        self._version = res

    def update_quantum(self):
        res = self._conn.command("getq")
        if len(res) != 1:
            raise Exception("unexpected response to getq command: " + str(res))

        self._quantum = int(res[0])

    def update_status(self):
        res = self._conn.command("status")
        if len(res) != 3:
            raise Exception("unexpected response to status command: " + str(res))

        status = res[0]
        if status == "running":
            self._running = True
            self._reason = ""
        elif status.startswith("stopped:"):
            self._running = False
            self._reason = status[8:]
        self._time = int(res[1])
        self._cycle = int(res[2])

    def update_modules(self):
        res = self._conn.command("list,xml")
        if len(res) != 1:
            raise Exception("unexpected response to l command: " + str(res))

        root = ElementTree.fromstring(res[0])
        if root.tag != "hierarchy":
            raise Exception("invalid hierarchy root node: " + root.tag)

        self.modules.clear()
        for subnode in root:
            if subnode.tag == "object":
                self.modules.append(Module(self._conn, None, subnode))
            elif subnode.tag == "target":
                self.targets.append(Target(self._conn, subnode))

    def running(self) -> bool:
        self.update_status()
        return self._running

    def sysc_version(self) -> str:
        return self._version[0]

    def vcml_version(self) -> str:
        return self._version[1]

    def time(self) -> int:
        self.update_status()
        return self._time

    def cycle(self) -> int:
        self.update_status()
        return self._cycle

    def reason(self) -> str:
        self.update_status()
        return self._reason

    def disconnect(self):
        for m in self.modules:
            m.disconnect()
        self._conn.disconnect()

    def kill(self):
        self._conn.send("quit")

    def step(self):
        self.update_status()
        if not self._running:
            self._running = True
            self._conn.command(f"resume,{self._quantum}ns")

        while self._running:
            self.update_status()

    def stepi(self, target):
        self.update_status()
        if not self._running:
            self._running = True
            self._conn.command(f"step,{target}")

        while self._running:
            self.update_status()

    def run(self):
        self.update_status()
        if not self._running:
            self._running = True
            self._conn.command("resume")

    def stop(self):
        self.update_status()
        if self._running:
            self._conn.command("stop")

    def create_breakpoint(self, target, addr) -> int:
        res = self._conn.command(f"mkbp,{target},{addr}")
        return int(res[0][20:])

    def delete_breakpoint(self, id):
        self._conn.command(f"rmbp,{id}")

    def dump(self):
        for m in self.modules:
            m.dump()

    def find_module(self, name):
        path = name if isinstance(name, list) else name.split(".")
        curr = None
        for m in self.modules:
            if m.name == path[0]:
                curr = m
                break
        if len(path) == 1 or not curr:
            return curr
        return curr.find_module(path[1:])

    def find_attribute(self, name):
        path = name if isinstance(name, list) else name.split(".")
        if len(path) == 1:
            return None
        m = self.find_module(path[:-1])
        return m.find_attribute(path[-1:]) if m else None

    def find_command(self, name):
        path = name if isinstance(name, list) else name.split(".")
        if len(path) == 1:
            return None
        m = self.find_module(path[:-1])
        return m.find_command(path[-1:]) if m else None

    def find_target(self, name):
        for t in self.targets:
            if t.name == str(name):
                return t
        return None
