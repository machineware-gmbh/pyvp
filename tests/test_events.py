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

import json
import socket
import threading
import xml.etree.ElementTree as ElementTree

import pytest
from conftest import SimpleVp, requires_simplevp

from vcml import TraceGpio, TraceTlm, format_trace
from vcml.connection import Connection
from vcml.dispatcher import Dispatcher
from vcml.events import TraceSpi, TraceUnknown, parse_payload
from vcml.module import Module

# the cpus run up to one quantum ahead, so a step of one quantum may execute nothing
STEP_NS = 10_000


@pytest.fixture
def vp():
    vp = SimpleVp(["-c", "system.cpu0.data.allow_dmi=false", "-c", "system.cpu1.data.allow_dmi=false"])
    yield vp
    vp.stop()


@pytest.fixture
def sess(vp):
    sess = vp.connect()

    sess._conn.command(["vwrite", "system.cpu0", "0", "0", "0", "0", "32"])

    yield sess
    sess.kill()
    sess.disconnect()


@requires_simplevp
def test_published_events(sess):
    assert sess.find_module("system.cpu0.data").is_traceable()
    assert "trace" in sess.find_module("system.cpu0.data").events
    assert sess.find_module("system.cpu0").is_traceable()
    assert not sess.find_module("system.cpu0").has_leds()
    assert not sess.find_module("system.cpu0").has_uart()


@requires_simplevp
def test_trace_tlm(sess):
    cpu = sess.find_module("system.cpu0")
    events = []

    cpu.on_trace(lambda info, tx: events.append((info, tx)), TraceTlm)
    assert cpu.is_traced()
    assert not sess.find_module("system.cpu1").is_traced()

    sess.step(STEP_NS)
    assert events

    data = sess.find_module("system.cpu0.data")
    for info, tx in events:
        assert info.port is data
        assert isinstance(tx, TraceTlm)
        assert tx.is_read()
        assert len(tx.data) == 4
        if info.is_response():
            assert tx.response == "TLM_OK_RESPONSE"

    assert any(info.is_request() for info, _ in events)
    assert any(info.is_response() for info, _ in events)
    assert sess.events_dropped() == 0

    cpu.on_trace(None, TraceTlm)
    assert not cpu.is_traced()
    count = len(events)
    sess.step(STEP_NS)
    assert len(events) == count


@requires_simplevp
def test_handlers_of_parents(sess):
    system = sess.find_module("system")
    cpu0 = sess.find_module("system.cpu0")

    step_ns = 2000

    senders = set()
    counts = {"system": 0, "cpu": 0}

    def on_system(info, tx):
        senders.add(info.port.hierarchy_name())
        if isinstance(tx, TraceTlm):
            counts["system"] += 1

    def on_cpu(info, tx):
        counts["cpu"] += 1

    system.on_trace(on_system)
    cpu0.on_trace(on_cpu, TraceTlm)

    sess.step(step_ns)
    assert counts["cpu"] > 0
    assert counts["system"] >= counts["cpu"]
    assert "system.cpu0.data" in senders
    assert "system.cpu1.data" in senders

    system.on_trace(None)
    assert not system.is_traced()
    assert cpu0.is_traced()

    before = counts["cpu"]
    counts["system"] = 0
    sess.step(step_ns)
    assert counts["cpu"] > before
    assert counts["system"] == 0


@requires_simplevp
def test_protocols_on_one_module(sess):
    cpu = sess.find_module("system.cpu0")
    tlm = []

    cpu.on_trace(lambda info, tx: tlm.append(tx), TraceTlm)
    cpu.on_trace(lambda info, tx: None, TraceGpio)

    cpu.on_trace(None, TraceGpio)
    assert cpu.is_traced()
    sess.step(STEP_NS)
    assert tlm


@requires_simplevp
def test_errors(sess):
    cpu = sess.find_module("system.cpu0")

    with pytest.raises(Exception, match="does not publish 'led' events"):
        cpu.on_led(lambda ev: None)
    with pytest.raises(Exception, match="does not publish 'uart' events"):
        cpu.on_uart(lambda ev: None)

    cpu.on_trace(None)
    cpu.on_led(None)

    sess.run()
    assert sess.running()
    with pytest.raises(Exception, match="simulation running"):
        cpu.on_trace(lambda info, tx: None, TraceTlm)
    assert not cpu.is_traced()
    sess.stop()
    assert not sess.running()


@requires_simplevp
def test_print_traces(sess):
    lines = []
    sess.find_module("system.cpu0").on_trace(lambda info, tx: lines.append(format_trace(info, tx)))
    sess.step(STEP_NS)
    assert lines
    assert "system.cpu0.data >> TLM READ @0x" in lines[0]


@requires_simplevp
def test_sessions(vp):
    info = next(s for s in vp.connect().local_sessions() if s.pid == vp.proc.pid)
    assert info.port == vp.port
    assert "simplevp" in info.program


class FakeServer:
    def __init__(self, respond=lambda cmd: "OK"):
        self.commands = []
        self._respond = respond
        self._server = socket.create_server(("localhost", 0))
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        client, _ = self._server.accept()
        buf = b""
        with client:
            while True:
                data = client.recv(4096)
                if not data:
                    return
                buf += data
                while True:
                    start = buf.find(b"$")
                    end = buf.find(b"#", start)
                    if start < 0 or end < 0 or len(buf) < end + 3:
                        break
                    cmd = buf[start + 1 : end].decode()
                    buf = buf[end + 3 :]
                    self.commands.append(cmd)
                    resp = self._respond(cmd).encode()
                    client.sendall(b"+$" + resp + b"#" + f"{sum(resp) % 256:02x}".encode())

    def close(self):
        self._server.close()


def module(conn, disp, parent, name, events=""):
    node = ElementTree.Element("object", {"name": name, "kind": "", "version": "", "events": events})
    m = Module(conn, parent, node, disp)
    if parent is not None:
        parent.modules.append(m)
    return m


class Tree:
    def __init__(self, respond=lambda cmd: "OK"):
        self.server = FakeServer(respond)
        self.conn = Connection(f"localhost:{self.server.port}")
        self.disp = Dispatcher(self.conn)
        self.top = module(self.conn, self.disp, None, "top")
        self.leds = module(self.conn, self.disp, self.top, "leds", "led")
        self.out = module(self.conn, self.disp, self.top, "out", "trace")
        self.term = module(self.conn, self.disp, self.top, "term", "uart")
        self.disp.set_modules({"top": self.top, "top.leds": self.leds, "top.out": self.out, "top.term": self.term})

    @property
    def commands(self):
        return self.server.commands

    def close(self):
        self.conn.disconnect()
        self.server.close()


@pytest.fixture
def tree():
    t = Tree()
    yield t
    t.close()


def event(name, sender, payload):
    return {"event": name, "sender": sender, "time": 10000, "delta": 4, "payload": payload}


def events(*evs, **kwargs):
    return json.dumps({"events": list(evs), **kwargs})


def test_subscribe(tree):
    tree.top.on_led(lambda ev: None)
    tree.top.on_led(lambda ev: None)
    tree.top.on_led(None)
    tree.top.on_trace(lambda info, tx: None)
    tree.top.on_trace(lambda info, tx: None, TraceTlm)
    tree.top.on_trace(None)
    assert tree.top.is_traced()
    assert tree.top.has_leds()
    assert tree.top.has_uart()
    assert not tree.leds.is_traceable()
    tree.leds.on_trace(None)
    assert tree.commands == ["sub,led,top.leds", "unsub,led,top.leds", "sub,trace,top.out"]


def test_shared_publishers(tree):
    def fn(info, tx):
        pass

    tree.top.on_trace(fn)
    tree.out.on_trace(fn)
    tree.top.on_trace(None)
    assert tree.commands == ["sub,trace,top.out"]

    tree.out.on_trace(None)
    assert tree.commands == ["sub,trace,top.out", "unsub,trace,top.out"]

    with pytest.raises(Exception, match=r"'top\.leds' does not publish 'trace' events"):
        tree.leds.on_trace(fn)
    assert not tree.leds.is_traced()


def test_leds(tree):
    seen = []

    def on_led(ev):
        assert ev.leds is tree.leds
        assert ev.time_ps == 10000
        assert ev.delta == 4
        seen.append(f"{ev.index}={int(ev.state)}")

    tree.top.on_led(on_led)
    tree.disp.dispatch(
        events(
            event("led", "top.leds", {"led": 2, "state": True}),
            event("led", "top.leds", {"led": 0, "state": False}),
        )
    )
    assert seen == ["2=1", "0=0"]


def test_traces(tree):
    addresses = []
    protocols = []
    gpio = []

    def on_tlm(info, tx):
        assert info.port is tree.out
        assert info.is_response()
        assert info.error
        addresses.append(tx.address)

    tree.top.on_trace(on_tlm, TraceTlm)
    tree.top.on_trace(lambda info, tx: gpio.append(tx), TraceGpio)
    tree.out.on_trace(lambda info, tx: protocols.append(tx.PROTOCOL))

    tlm = {
        "dir": "bw",
        "protocol": "TLM",
        "error": True,
        "tx": {
            "address": 2**64 - 1,
            "data": [1],
            "command": "READ",
            "byte_enable": [],
            "streaming_width": 1,
            "dmi_allowed": False,
            "response_status": "TLM_OK_RESPONSE",
        },
    }
    spi = {"dir": "fw", "protocol": "SPI", "error": False, "tx": {"mosi": 1, "miso": 2}}
    bad = {"dir": "fw", "protocol": "TLM", "error": False, "tx": {"address": 16}}
    newp = {"dir": "fw", "protocol": "NEWPROTO", "error": False, "tx": {}}
    tree.disp.dispatch(
        events(
            event("trace", "top.out", tlm),
            event("trace", "top.out", spi),
            event("trace", "top.out", bad),
            event("trace", "top.out", newp),
        )
    )

    assert addresses == [2**64 - 1]
    assert gpio == []
    assert protocols == ["TLM", "SPI", "UNKNOWN"]


def test_uart(tree):
    data = []

    def on_uart(ev):
        assert ev.terminal is tree.term
        assert ev.time_ps == 10000
        data.append(ev.data)

    tree.top.on_uart(on_uart)

    tree.disp.dispatch(
        events(
            event("uart", "top.term", "h"),
            event("uart", "top.term", "i"),
            event("uart", "top.term", "\n"),
            event("led", "top.leds", {"led": 0, "state": True}),
            event("uart", "top.term", "ÿ"),
            event("uart", "top.term", "\u0000"),
        )
    )
    assert data == [b"hi\n", b"\xff\x00"]


def test_dropped_and_unknown(tree, capsys):
    dropped = []
    count = []
    tree.disp.on_dropped(dropped.append)
    tree.top.on_led(count.append)

    tree.disp.dispatch(events(event("led", "top.nothing", {}), dropped=3))
    tree.disp.dispatch(events())
    tree.disp.dispatch("garbage")

    assert dropped == [3]
    assert tree.disp.dropped() == 3
    assert count == []
    assert "unknown object 'top.nothing'" in capsys.readouterr().err


def test_unsupported():
    t = Tree(lambda cmd: "")
    with pytest.raises(Exception, match="not supported"):
        t.out.on_trace(lambda info, tx: None)
    assert not t.out.is_traced()
    t.close()


def test_not_connected(tree):
    tree.conn.disconnect()
    with pytest.raises(Exception, match="not connected"):
        tree.out.on_trace(lambda info, tx: None)


def test_print_payloads():
    assert str(TraceSpi(1, 2)) == "SPI mosi=0x01 miso=0x02"
    assert str(TraceTlm("WRITE", 16, bytes([0x11, 0, 0, 0]), b"", 4, False, "TLM_OK_RESPONSE")) == (
        "TLM WRITE @0x10 [11 00 00 00] TLM_OK_RESPONSE"
    )
    assert str(TraceUnknown("NEWPROTO")) == "NEWPROTO"


def test_parse_tlm():
    tx = parse_payload(
        "TLM",
        json.loads(
            '{"address":16,"data":[17,0,0,0],"command":"WRITE",'
            '"byte_enable":[255],"streaming_width":4,"dmi_allowed":true,'
            '"response_status":"TLM_OK_RESPONSE","sbi":{"is_debug":true,'
            '"is_nodmi":false,"is_sync":false,"is_insn":true,"is_excl":false,'
            '"is_lock":false,"is_secure":true,"atype":"untranslated",'
            '"cpuid":1,"privilege":3,"asid":18446744073709551615}}'
        ),
    )
    assert isinstance(tx, TraceTlm)
    assert tx.is_write()
    assert tx.address == 16
    assert tx.data == bytes([17, 0, 0, 0])
    assert tx.byte_enable == bytes([255])
    assert tx.streaming_width == 4
    assert tx.dmi_allowed
    assert tx.sbi.is_debug
    assert tx.sbi.is_insn
    assert tx.sbi.cpuid == 1
    assert tx.sbi.asid == 2**64 - 1

    assert parse_payload("TLM", {"address": 16}) is None
    assert parse_payload("TLM", "garbage") is None


def parse(protocol, text):
    return parse_payload(protocol, json.loads(text))


def test_parse_others():
    gpio = parse("GPIO", '{"state":true,"vector":3}')
    assert gpio.state and gpio.vector == 3
    assert parse("GPIO", '{"state":false}').vector is None

    clk = parse("CLK", '{"period":10,"polarity":"posedge","duty_cycle":0.5}')
    assert clk.period_ns == 10 and clk.posedge and clk.duty_cycle == 0.5

    pci = parse(
        "PCI",
        '{"command":"PCI_READ","response":"PCI_RESP_SUCCESS","address_space":"PCI_AS_CFG","address":4,"data":[1,2],"debug":false}',
    )
    assert pci.address_space == "PCI_AS_CFG" and pci.data == bytes([1, 2])

    assert parse("I2C", '{"command":"I2C_START","response":"I2C_ACK","data":80}').data == 80
    assert parse("LIN", '{"linid":5,"data":[1,2,3],"status":"LIN_SUCCESS"}').linid == 5

    spi = parse("SPI", '{"miso":1,"mosi":2}')
    assert spi.miso == 1 and spi.mosi == 2

    sd = parse("SD", '{"command":"SD_CMD","opcode":"CMD17","argument":512,"crc":3,"spi":false,"response":[0,1],"status":"SD_OK"}')
    assert sd.opcode == "CMD17" and sd.argument == 512 and sd.data == bytes([0, 1])
    sd = parse("SD", '{"command":"SD_DATA_READ","data":66,"status":"SDTX_OK"}')
    assert sd.opcode == "" and sd.data == bytes([66])

    virtio = parse(
        "VIRTIO", '{"index":1,"input_buffers":[{"addr":18446744073709551615,"size":8}],"output_buffers":[],"status":"VIRTIO_OK"}'
    )
    assert virtio.input_buffers[0].addr == 2**64 - 1 and virtio.output_buffers == []

    assert parse("SERIAL", '{"data":65,"bits":8,"baud":115200,"parity":"none","stop":"1"}').baud == 115200

    assert parse("SIGNAL", '{"data":5}').data == 5
    assert parse("SIGNAL", '{"data":-5}').data == -5
    assert parse("SIGNAL", '{"data":1.5}').data == 1.5
    assert parse("SIGNAL", '{"data":true}').data is True
    assert parse("SIGNAL", '{"data":"123456789012345678901234"}').data == "123456789012345678901234"
    assert parse("SIGNAL", '{"data":null}').data is None

    eth = parse("ETHERNET", '{"type":"IPv4","sourceaddr":"11:22:33:44:55:66","destaddr":"ff:ff:ff:ff:ff:ff","data":[1,2]}')
    assert eth.source == "11:22:33:44:55:66"
    assert parse("ETHERNET", '{"type":"invalid"}').source == ""

    can = parse("CAN", '{"type":"CAN_FD","id":291,"xlf":false,"fdf":true,"eff":false,"brs":true,"esi":false,"data":[1,2,3]}')
    assert can.id == 291 and can.brs and not can.rtr

    usb = parse("USB", '{"token":"USB_TOKEN_IN","addr":1,"endpoint":2,"data":[9],"status":"USB_RESULT_SUCCESS"}')
    assert usb.endpoint == 2

    assert parse("NEWPROTO", "{}") == TraceUnknown("NEWPROTO")
