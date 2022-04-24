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
        self._time: int = 0
        self._cycle: int = 0

        self._conn = Connection(address)
        self.modules = []
        self.targets = []

        self.update_version()
        self.update_time()
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
        res = self._conn.command("v")
        if len(res) != 2:
            raise Exception("unexpected response to v command: " + str(res))

        self._version = res

    def update_time(self):
        if self._running:
            self._conn.signal("u")
            res = self._conn.recv().split(",")
            if len(res) != 3 or res[0] != "OK":
                raise Exception("unexpected response to t signal " + str(res))
            res = res[1:]
        else:
            res = self._conn.command("t")
            if len(res) != 2:
                raise Exception("unexpected response to t command: " + str(res))

        self._time = int(res[0])
        self._cycle = int(res[1])

    def update_modules(self):
        res = self._conn.command("l")
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
        return self._running

    def sysc_version(self) -> str:
        return self._version[0]

    def vcml_version(self) -> str:
        return self._version[1]

    def time(self) -> int:
        return self._time

    def cycle(self) -> int:
        return self._cycle

    def disconnect(self):
        for m in self.modules:
            m.disconnect()
        self._conn.disconnect()

    def kill(self):
        self._conn.send("x")

    def step(self):
        res = self._conn.command("s")
        if len(res) != 0:
            raise Exception("unexpected response to s command: " + str(res))

        self.update_time()

    def _do_run(self):
        self._conn.send("c")

        while self._running:
            self.update_time()
            time.sleep(0.1)

        self._conn.signal("a")
        res = self._conn.recv()
        if "OK" not in res:
            raise Exception("unexpected response from simulation " + str(res))

    def run(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._do_run)
            self._thread.start()

    def stop(self):
        if self._running:
            self._running = False
            self._thread.join()

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

