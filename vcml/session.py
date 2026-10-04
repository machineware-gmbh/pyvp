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

import contextlib
import getpass
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

from .connection import Connection
from .dispatcher import Dispatcher
from .module import Module
from .target import Target


@dataclass
class SessionInfo:
    host: str
    port: int
    pid: int
    user: str
    program: str

    def address(self) -> str:
        return f"{self.host}:{self.port}"


def process_exists(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # the process exists but belongs to another user
            return ctypes.GetLastError() == 5  # ERROR_ACCESS_DENIED
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return not ok or code.value == STILL_ACTIVE

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # the process exists but belongs to another user
    return True


class Session:
    def __init__(self, address: str):
        self._version: list[str] = ["unknown", "unknown", "0"]
        self._running: bool = False
        self._reason: str = ""
        self._time: int = 0
        self._cycle: int = 0
        self._quantum: int = 0
        self._conn: Connection = Connection(address)
        self._dispatcher: Dispatcher = Dispatcher(self._conn)
        self.modules = []
        self.targets = []

        self.update_version()
        self.stop()
        self.update_quantum()
        self.update_modules()

    def __str__(self):
        return self.peer()

    def peer(self):
        return self._conn.peer()

    def update_version(self):
        res = self._conn.command(["version"])
        if len(res) == 2:  # old vspserver -> no protover
            res.append("0")

        if len(res) != 3:
            raise Exception("unexpected response to version command: " + str(res))

        self._version = res

    def update_quantum(self):
        res = self._conn.command(["getq"])
        if len(res) != 1:
            raise Exception("unexpected response to getq command: " + str(res))

        self._quantum = int(res[0])

    def update_status(self):
        res = self._conn.command(["status"])
        if len(res) not in (3, 4):
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

        if len(res) > 3:
            self._dispatcher.dispatch(res[3])

    def update_modules(self):
        res = self._conn.command(["list", "xml"])
        if len(res) != 1:
            raise Exception("unexpected response to l command: " + str(res))

        root = ElementTree.fromstring(res[0])
        if root.tag != "hierarchy":
            raise Exception("invalid hierarchy root node: " + root.tag)

        self.modules.clear()
        self.targets.clear()
        for subnode in root:
            if subnode.tag == "object":
                self.modules.append(Module(self._conn, None, subnode, self._dispatcher))
            elif subnode.tag == "target":
                self.targets.append(Target(self._conn, subnode))

        modules = {}

        def add(m):
            modules[m.hierarchy_name()] = m
            for child in m.modules:
                add(child)

        for m in self.modules:
            add(m)
        self._dispatcher.set_modules(modules)

    def running(self) -> bool:
        self.update_status()
        return self._running

    def sysc_version(self) -> str:
        return self._version[0]

    def vcml_version(self) -> str:
        return self._version[1]

    def prot_version(self) -> str:
        return self._version[2]

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

    def step(self, ns: int = 0):
        self.update_status()
        if not self._running:
            self._running = True
            self._conn.command(["resume", f"{ns or self._quantum}ns"])

        while self._running:
            self.update_status()

    def stepi(self, target):
        self.update_status()
        if not self._running:
            self._running = True
            self._conn.command(["step", str(target)])

        while self._running:
            self.update_status()

    def run(self):
        self.update_status()
        if not self._running:
            self._running = True
            self._conn.command(["resume"])

    def stop(self):
        self.update_status()
        if self._running:
            self._conn.command(["stop"])
            while self._running:
                self.update_status()

    def on_events_dropped(self, fn):
        self._dispatcher.on_dropped(fn)

    def events_dropped(self) -> int:
        return self._dispatcher.dropped()

    @staticmethod
    def local_sessions() -> list[SessionInfo]:
        sessions = []
        orphans = []
        tmpdir = tempfile.gettempdir()
        try:
            user = getpass.getuser()
        except Exception:
            user = ""

        try:
            entries = os.listdir(tmpdir)
        except OSError:
            return sessions

        for entry in entries:
            match = re.fullmatch(r"vcml_session_(\d+)", entry)
            if not match:
                continue

            path = os.path.join(tmpdir, entry)
            try:
                with open(path, encoding="utf-8") as f:
                    lines = [line.strip() for line in f.read().splitlines()]
                if len(lines) < 2 or not lines[0]:
                    continue
                host = lines[0]
                port = int(lines[1])
            except (OSError, ValueError):
                continue

            owner = lines[2] if len(lines) > 2 else ""
            program = lines[3] if len(lines) > 3 else ""
            pid = int(match[1])

            if not process_exists(pid):
                if user and owner == user:
                    orphans.append(path)
                continue

            sessions.append(SessionInfo(host, port, pid, owner, program))

        for orphan in orphans:
            with contextlib.suppress(OSError):
                os.remove(orphan)

        return sessions

    def create_breakpoint(self, target, addr) -> int:
        res = self._conn.command(["mkbp", str(target), str(addr)])
        return int(res[0][20:])

    def delete_breakpoint(self, id):
        self._conn.command(["rmbp", str(id)])

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
