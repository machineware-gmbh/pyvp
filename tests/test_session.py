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

import contextlib
import getpass
import os
import subprocess
import sys
import tempfile

import pytest
from conftest import SimpleVp, requires_simplevp

from vcml import Session, SessionInfo

USER = getpass.getuser()

LIVE_A = os.getpid()
LIVE_B = os.getppid()


def dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


@pytest.fixture
def announce():
    created = []

    def write(name, content):
        path = os.path.join(tempfile.gettempdir(), name if isinstance(name, str) else f"vcml_session_{name}")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        created.append(path)
        return path

    yield write

    for path in created:
        with contextlib.suppress(OSError):
            os.remove(path)


def find(pid):
    return next((s for s in Session.local_sessions() if s.pid == pid), None)


def test_parses_session_file(announce):
    announce(LIVE_A, f"localhost\n5555\n{USER}\n/path/to/vp\n")
    assert find(LIVE_A) == SessionInfo("localhost", 5555, LIVE_A, USER, "/path/to/vp")
    assert find(LIVE_A).address() == "localhost:5555"


def test_parses_crlf(announce):
    announce(LIVE_A, "localhost\r\n6666\r\n")
    assert find(LIVE_A) == SessionInfo("localhost", 6666, LIVE_A, "", "")


def test_ignores_other_files(announce):
    announce("not_a_session_file", "localhost\n7777\n")
    announce("vcml_session_unit_test", "localhost\n7777\n")
    assert all(s.port != 7777 for s in Session.local_sessions())


def test_ignores_malformed_files(announce):
    announce(LIVE_A, "localhost\n")
    announce(LIVE_B, "localhost\nnotaport\n")
    assert find(LIVE_A) is None
    assert find(LIVE_B) is None


def test_multiple_sessions(announce):
    announce(LIVE_A, "localhost\n9991\n")
    announce(LIVE_B, "localhost\n9992\n")
    assert find(LIVE_A).port == 9991
    assert find(LIVE_B).port == 9992


def test_removes_orphans_of_current_user(announce):
    pid = dead_pid()
    path = announce(pid, f"localhost\n9993\n{USER}\n/path/to/vp\n")
    assert find(pid) is None
    assert not os.path.exists(path)


def test_keeps_orphans_of_other_users(announce):
    pid = dead_pid()
    path = announce(pid, "localhost\n9994\nsomeone-else\n/path/to/vp\n")
    assert find(pid) is None
    assert os.path.exists(path)


@requires_simplevp
def test_connect():
    vp = SimpleVp()
    try:
        sess = vp.connect()
        assert sess.vcml_version().startswith("vcml-")
        assert not sess.running()
        assert sess.find_module("system.cpu0") is not None

        sess.step(1000)
        assert sess.time() >= 1000
        sess.run()
        assert sess.running()
        sess.stop()
        assert not sess.running()

        sess.kill()
        sess.disconnect()
    finally:
        vp.stop()
