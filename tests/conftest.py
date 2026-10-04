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
import os
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vcml import Session

TIMEOUT_S = 10.0

SIMPLEVP = os.environ.get("SIMPLEVP", "")

requires_simplevp = pytest.mark.skipif(not SIMPLEVP, reason="set SIMPLEVP to the path of a simplevp binary")


class SimpleVp:
    def __init__(self, extra=()):
        self.proc = subprocess.Popen([SIMPLEVP, "--session", *extra], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.port = 0

        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            for info in Session.local_sessions():
                if info.pid == self.proc.pid and info.port != 0:
                    self.port = info.port
                    return
            time.sleep(0.01)

        self.stop()
        raise Exception("simplevp did not announce its session")

    def address(self):
        return f"localhost:{self.port}"

    def connect(self):
        deadline = time.monotonic() + TIMEOUT_S
        while True:
            try:
                return Session(self.address())
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

        # a killed simulator cannot remove its announce file
        with contextlib.suppress(OSError):
            os.remove(os.path.join(tempfile.gettempdir(), f"vcml_session_{self.proc.pid}"))
