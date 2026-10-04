#!/usr/bin/env python3

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
import sys
import time
from collections import namedtuple

import vcml
from vcml import Session

try:
    import readline  # noqa: F401

    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

HIGHLIGHT = BOLD + GREEN
TIMESTAMP = DIM
SESSION = BOLD + CYAN
MODULE = CYAN
COMMAND = GREEN
ATTRIBUTE = YELLOW


LED_SYMBOLS_UNICODE = {True: "\u25cf", False: "\u25cb", None: "\u00b7"}
LED_SYMBOLS_ASCII = {True: "*", False: ".", None: "?"}


def use_unicode() -> bool:
    return (sys.stdout.encoding or "").lower().replace("-", "") == "utf8"


def publishers(mod, event):
    found = [mod] if event in mod.events else []
    for child in mod.modules:
        found += publishers(child, event)
    return found


def read_led_states(leds):
    states = []
    cmd = leds.find_command("status")
    try:
        text = "\n".join(cmd.execute([])) if cmd else ""
    except Exception:
        text = ""
    for match in re.finditer(r"LED(\d+): (on|off)", text):
        idx = int(match[1])
        states += [None] * (idx + 1 - len(states))
        states[idx] = match[2] == "on"
    return states


def escape_text(data: bytes) -> str:
    out = ""
    for c in data:
        if c == 0x09 or 0x20 <= c < 0x7F:
            out += chr(c)
        else:
            out += f"\\x{c:02x}"
    return out


def escape_uart(data: bytes) -> str:
    out = ""
    for c in data:
        if c == 0x0A:
            out += "\\n"
        elif 0x20 <= c < 0x7F:
            out += chr(c)
        else:
            out += f"\\x{c:02x}"
    return out


class Application:
    def __init__(self):
        self.session: Session | None = None
        self.current: vcml.Module | None = None
        self.prevcmd = ["none"]
        self.subscriptions = []
        self.led_states = {}
        self.term_lines = {}
        self.event_log = None

        Handler = namedtuple("Handler", "func needs_session desc")
        self.commands = {
            "connect": Handler(self.handle_connect, False, "connect to a local simulation on <port> or to a remote one on <host>:<port>"),
            "disconnect": Handler(self.handle_disconnect, True, "disconnect from the current session without terminating it"),
            "quit": Handler(self.handle_quit, False, "disconnect from session and quit program"),
            "kill": Handler(self.handle_kill, True, "terminate current session"),
            "info": Handler(self.handle_info, True, "print information about the current session"),
            "step": Handler(self.handle_step, True, "advances simulation to the next discrete timestamp"),
            "stepi": Handler(self.handle_stepi, True, "step target one instruction"),
            "run": Handler(self.handle_run, True, "continues simulation, use CTRL+C to interrupt"),
            "list": Handler(self.handle_list, True, "displays the module hierarchy onwards from current module"),
            "cd": Handler(self.handle_cd, True, "moves current module to <module>"),
            "exec": Handler(self.handle_exec, True, "executes the given <command> [args...]"),
            "read": Handler(self.handle_read, True, "reads the given <attribute>"),
            "break": Handler(self.handle_break, True, "sets a breakpoint for the given target"),
            "delete": Handler(self.handle_delete, True, "delete a breakpoint with the given ID"),
            "events": Handler(
                self.handle_events, True, "simulation events: add|rm trace|led|uart <module>..., log [file]; no arguments shows the status"
            ),
            "trace": Handler(self.handle_trace, True, "traces all ports of the given modules, or of the current module"),
            "untrace": Handler(self.handle_trace, True, "stops tracing the given modules, or the current module"),
            "watch": Handler(self.handle_watch, True, "shows the leds of the given modules, or of the current module"),
            "unwatch": Handler(self.handle_watch, True, "stops watching the leds of the given modules, or of the current module"),
            "follow": Handler(self.handle_follow, True, "shows the terminal output of the given modules, or of the current module"),
            "unfollow": Handler(self.handle_follow, True, "stops following the terminals of the given modules, or of the current module"),
            "sessions": Handler(self.handle_sessions, False, "lists local simulation sessions"),
            "help": Handler(self.handle_help, False, "prints this message"),
            "ll": Handler(self.handle_ll, True, "long listing: modules with kind, commands with description, attributes with type"),
        }

        self.aliases = {
            "t": "connect",
            "d": "disconnect",
            "i": "info",
            "s": "step",
            "si": "stepi",
            "c": "run",
            "k": "kill",
            "q": "quit",
            "l": "list",
            "ls": "list",
            "x": "exec",
            "r": "read",
            "b": "break",
            "h": "help",
        }

        self.help = []
        for c in self.commands:
            alias = [k for k, v in self.aliases.items() if str(v) == c]
            self.help.append([c, *alias])

        self._setup_readline()

        try:
            if len(sys.argv) >= 2:
                self.execute(["connect", *sys.argv[-1:]])
        except Exception as err:
            print(f"\n{RED}{err}{RESET}")

    def _setup_readline(self):
        if not HAS_READLINE:
            return
        import readline

        readline.set_completer(self.completer)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")

    def _complete_module_path(self, base, partial):
        dot = partial.rfind(".")
        if dot == -1:
            return [m.name for m in base.modules if m.name.startswith(partial)]
        prefix = partial[: dot + 1]
        segment = partial[dot + 1 :]
        parent = base.find_module(partial[:dot])
        if not parent:
            return []
        return [prefix + m.name for m in parent.modules if m.name.startswith(segment)]

    def completer(self, text, state):
        try:
            import readline

            line = readline.get_line_buffer()
            tokens = line.split()
            at_boundary = not line or line[-1].isspace()
            prefix_tokens = tokens if at_boundary else tokens[:-1]

            candidates = []

            if len(prefix_tokens) == 0:
                builtins = list(self.commands.keys()) + list(self.aliases.keys())
                mod_cmds = [c.name for c in self.current.commands] if self.current else []
                attr_names = [a.name for a in self.current.attributes] if self.current else []
                seen = set()
                all_cands = []
                for c in builtins + mod_cmds + attr_names:
                    if c not in seen:
                        seen.add(c)
                        all_cands.append(c)
                candidates = [c for c in all_cands if c.startswith(text)]
            else:
                first = prefix_tokens[0]
                cmd = self.aliases.get(first, first)

                if cmd == "read" and self.current:
                    candidates = [a.name for a in self.current.attributes if a.name.startswith(text)]
                elif cmd == "exec" and self.current:
                    candidates = [c.name for c in self.current.commands if c.name.startswith(text)]
                elif cmd in ("stepi", "break") and self.session:
                    candidates = [t.name for t in self.session.targets if t.name.startswith(text)]
                elif cmd == "connect" and len(prefix_tokens) == 1:
                    candidates = [s.address() for s in Session.local_sessions() if s.address().startswith(text)]
                elif cmd == "events" and len(prefix_tokens) == 1:
                    candidates = [c for c in ("add", "rm", "log") if c.startswith(text)]
                elif cmd == "events" and len(prefix_tokens) == 2 and prefix_tokens[1] in ("add", "rm"):
                    candidates = [c for c in ("trace", "led", "uart") if c.startswith(text)]
                elif self.session and (
                    cmd in ("trace", "untrace", "watch", "unwatch", "follow", "unfollow") or (cmd == "events" and len(prefix_tokens) > 2)
                ):
                    base = self.current if self.current else self.session
                    candidates = self._complete_module_path(base, text)
                elif cmd == "cd" and self.session and len(prefix_tokens) == 1:
                    if "..".startswith(text):
                        candidates.append("..")
                    base = self.current if self.current else self.session
                    candidates += self._complete_module_path(base, text)

            return candidates[state] if state < len(candidates) else None
        except Exception:
            return None

    def find_module(self, name):
        m = None
        if self.current:
            m = self.current.find_module(name)
        if self.session and not m:
            m = self.session.find_module(name)
        return m

    def find_attribute(self, name):
        cmd = None
        if self.current:
            cmd = self.current.find_attribute(name)
        if self.session and not cmd:
            cmd = self.session.find_attribute(name)
        return cmd

    def find_command(self, name):
        cmd = None
        if self.current:
            cmd = self.current.find_command(name)
        if self.session and not cmd:
            cmd = self.session.find_command(name)
        return cmd

    def prompt(self):
        sys.stdout.write("\n")
        if self.session:
            sys.stdout.write(f"{TIMESTAMP}[{self.session.time() / 1e9:.9f}s]{RESET}")
            sys.stdout.write(" " + SESSION + str(self.session) + RESET)
            if self.current:
                sys.stdout.write(f" {MODULE + str(self.current) + RESET}")
            sys.stdout.write("\n")
        else:
            print(f"{RED + BOLD}[ no session ]{RESET}")
        sys.stdout.flush()

    def run(self):
        while True:
            try:
                self.prompt()
                args = input("> ").split()
                self.execute(args)

            except KeyboardInterrupt:
                sys.stdout.write("\nquit\n")
                return

            except EOFError:
                sys.stdout.write("\nquit\n")
                return

            except Exception as err:
                print(f"\n{RED}{err}{RESET}")
                if isinstance(err, OSError):
                    self.session = None
                    self.current = None

    def execute(self, args):
        if not args:
            args = self.prevcmd

        overlay_command = self.find_command(args[0])
        if overlay_command:
            args = ["exec", *args]
        elif args[0] not in self.commands and args[0] not in self.aliases:
            overlay_attribute = self.find_attribute(args[0])
            if overlay_attribute:
                args = ["read", *args]

        command = self.aliases.get(args[0], args[0])
        handler = self.commands.get(command)

        if not handler:
            raise Exception(f"unknown command '{command}', try 'help'")

        if not self.session and handler.needs_session:
            raise Exception("not connected, use 'connect [host]:<port>'")

        handler.func(args)
        self.prevcmd = args

    def handle_connect(self, args):
        if len(args) != 2:
            raise Exception(f"usage: {args[0]} [host]:<port>")

        if self.session:
            self.handle_disconnect(args)

        addr = args[1] if ":" in args[1] else "localhost:" + args[1]
        print(f"connecting to {addr}...")
        self.session = Session(addr)
        self.session.on_events_dropped(lambda n: self.print_event(f"--- {n} events dropped ---"))
        print("connected to " + self.session.peer())

    def handle_disconnect(self, args):
        assert self.session
        print("disconnecting from session " + str(self.session))
        self.session.disconnect()
        self.current = None
        self.session = None
        self.subscriptions = []
        self.led_states = {}
        self.term_lines = {}

    def handle_quit(self, args):
        exit(int(args[1]) if len(args) > 1 else 0)

    def handle_kill(self, args):
        assert self.session
        print("terminating session " + str(self.session))
        self.session.kill()
        self.current = None
        self.session = None
        self.subscriptions = []
        self.led_states = {}
        self.term_lines = {}

    def handle_step(self, args):
        assert self.session
        self.session.step()

    def handle_stepi(self, args):
        assert self.session
        if len(args) == 2:
            name = self.session.find_target(args[1])
        else:
            name = self.current

        target = self.session.find_target(name)
        if not target:
            raise Exception(f"No such target: {name}")
        self.session.stepi(target)

    def handle_run(self, args: list[str]):
        assert self.session
        self.session.run()
        stop_reason = "unknown"
        try:
            while self.session.running():
                time.sleep(0.1)
                sys.stdout.write(
                    "\033[1000D{}{:<16}{}{:.9f}s | {}".format(
                        HIGHLIGHT,
                        "Simulating...",
                        RESET,
                        self.session.time() / 1e9,
                        self.session.cycle(),
                    )
                )
                sys.stdout.flush()

            stop_reason = self.session.reason()
        except KeyboardInterrupt:
            self.session.stop()
        except OSError as err:
            self.current = None
            self.session = None
            stop_reason = str(err)
        print()
        self.flush_terminals()
        print(f"Stopped by {stop_reason}")

    def handle_info(self, args):
        assert self.session
        reports = {
            "Simulation Host": self.session.peer(),
            "VCML Version": self.session.vcml_version(),
            "SystemC Version": self.session.sysc_version(),
            "Proto. Version": self.session.prot_version(),
            "Simulation Time": f"{self.session.time() / 1e9:.9f}s",
            "Delta Cycle": f"{self.session.cycle()}",
        }

        for r in reports:
            print(f"{BOLD + WHITE}{r:<16}{RESET}{WHITE}{reports[r]}{RESET}")

    def handle_list(self, args):
        assert self.session
        show_mods = "-m" in args
        show_attr = "-a" in args
        show_cmds = "-c" in args

        if not show_mods and not show_attr and not show_cmds:
            show_mods = True
            show_attr = True
            show_cmds = True

        mods = []
        attr = []
        cmds = []

        if show_mods:
            if self.current:
                mods = self.current.modules
            else:
                mods = self.session.modules

        if show_attr and self.current:
            attr = self.current.attributes
        if show_cmds and self.current:
            cmds = self.current.commands

        outputs = []
        for m in mods:
            outputs.append(f"{MODULE}{m.name + self.event_marks(m):<20}{RESET}")
        for c in cmds:
            outputs.append(f"{COMMAND}{c.name:<20}{RESET}")
        for a in attr:
            outputs.append(f"{ATTRIBUTE}{a.name:<20}{RESET}")

        for i, s in enumerate(outputs):
            print(s, end="")
            if i % 5 == 4:
                print("")
        print("")

    def handle_ll(self, args):
        assert self.session
        mods = self.current.modules if self.current else self.session.modules
        cmds = self.current.commands if self.current else []
        attr = self.current.attributes if self.current else []

        for m in mods:
            line = f"{MODULE}{m.name}{RESET}"
            if m.kind:
                line += f" {DIM}({m.kind}){RESET}"
            line += self.event_marks(m)
            print(line)
        for c in cmds:
            print(f"{COMMAND}{c.name}{RESET} {DIM}- {c.desc}{RESET}")
        for a in attr:
            type_str = f"{a.type}[{a.count}]" if a.count > 1 else a.type
            print(f"{ATTRIBUTE}{a.name}{RESET} {DIM}({type_str}){RESET}")

    def handle_cd(self, args):
        if len(args) > 2:
            raise Exception(f"Usage: {args[0]} [module|..]")

        if len(args) == 1:
            self.current = None
            return

        if args[1] == "..":
            if self.current is not None:
                self.current = self.current.parent
            return

        m = self.find_module(args[1])
        if not m:
            raise Exception(f"no such module: {args[1]}")
        self.current = m

    def handle_exec(self, args):
        if len(args) < 2:
            raise Exception(f"usage: {args[0]} <command> [args...]")

        name = args[1]
        args = args[2:]
        cmd = self.find_command(name)
        if not cmd:
            raise Exception(f"no such command: {name}")

        for res in cmd.execute(args):
            print(str(res))

    def handle_read(self, args):
        if not self.current:
            return

        if len(args) < 2:
            attrs = self.current.attributes
        else:
            attrs = []
            for arg in args[1:]:
                a = self.find_attribute(arg)
                if not a:
                    raise Exception(f"no such attribute: {arg}")
                attrs.append(a)

        for attr in attrs:
            val = attr.get()
            print(f"{ATTRIBUTE}{attr.name:<16}{RESET}{val!s}")

    def handle_break(self, args):
        assert self.session
        if len(args) < 2:
            raise Exception(f"usage: {args[0]} <address> [targets]")

        addr = args[1]
        targets = []
        for name in args[2:]:
            targets.append(self.session.find_target(name))

        if len(args) == 2:
            targets = self.session.targets

        for target in targets:
            id = self.session.create_breakpoint(target, addr)
            print(f"Created breakpoint {id} on target {target}")

    def handle_delete(self, args):
        assert self.session
        if len(args) < 2:
            raise Exception(f"usage: {args[0]} <id> [id...]")

        for id in args[1:]:
            print(f"deleting breakpoint {id}")
            self.session.delete_breakpoint(id)

    def event_marks(self, mod):
        return "".join(f" [{event}]" for event, m in self.subscriptions if m is mod)

    def print_event(self, line):
        if self.event_log:
            self.event_log.write(line + "\n")
            return
        sys.stdout.write("\033[1000D\033[K" + line + "\n")

    def handle_events(self, args):
        assert self.session
        if len(args) == 1:
            reports = {
                "Output": "file" if self.event_log else "console",
                "Dropped": str(self.session.events_dropped()),
            }
            for r in reports:
                print(f"{BOLD + WHITE}{r:<16}{RESET}{WHITE}{reports[r]}{RESET}")
            for event, mod in self.subscriptions:
                print(f"{BOLD + WHITE}{event:<16}{RESET}{WHITE}{mod}{RESET}")
            return

        if args[1] == "log":
            if self.event_log:
                self.event_log.close()
                self.event_log = None
            if len(args) > 2:
                self.event_log = open(args[2], "w", encoding="utf-8")  # noqa: SIM115
            return

        if args[1] not in ("add", "rm"):
            raise Exception(f"unknown events command '{args[1]}'")
        if len(args) < 4:
            raise Exception(f"usage: {args[0]} {args[1]} trace|led|uart <module>...")

        enable = args[1] == "add"
        event = args[2]
        if event not in ("trace", "led", "uart"):
            raise Exception(f"unknown event '{event}', use trace, led or uart")

        for name in args[3:]:
            mod = self.find_module(name)
            if not mod:
                raise Exception(f"no such module: {name}")
            self.select_event(event, mod, enable)

    def select_event(self, event, mod, enable):
        if event == "trace":
            mod.on_trace((lambda info, tx: self.print_event(vcml.format_trace(info, tx))) if enable else None)
        elif event == "led":
            mod.on_led(
                (lambda ev: self.print_event(f"{vcml.format_time(ev.time_ps)} {ev.leds} led {ev.index}={int(ev.state)}"))
                if enable
                else None
            )
        else:
            mod.on_uart(
                (lambda ev: self.print_event(f'{vcml.format_time(ev.time_ps)} {ev.terminal} uart "{escape_uart(ev.data)}"'))
                if enable
                else None
            )

        self.subscriptions = [(e, m) for e, m in self.subscriptions if e != event or m is not mod]
        if enable:
            self.subscriptions.append((event, mod))

    def resolve_modules(self, names, at_top):
        assert self.session
        mods = []
        for name in names or ["."]:
            if name != ".":
                mod = self.find_module(name)
                if not mod:
                    raise Exception(f"no such module: {name}")
                mods.append(mod)
            elif self.current:
                mods.append(self.current)
            else:
                mods += [m for m in self.session.modules if at_top(m)]
        return mods

    def handle_trace(self, args):
        for mod in self.resolve_modules(args[1:], lambda m: m.is_traceable()):
            self.select_event("trace", mod, args[0] == "trace")

    def handle_watch(self, args):
        enable = args[0] == "watch"
        for mod in self.resolve_modules(args[1:], lambda m: m.has_leds()):
            if enable and not mod.has_leds():
                hint = ", use 'follow' for terminals" if mod.has_uart() else ""
                raise Exception(f"'{mod}' has no leds{hint}")
            for leds in publishers(mod, "led"):
                self.watch_leds(leds, enable)

    def handle_follow(self, args):
        enable = args[0] == "follow"
        for mod in self.resolve_modules(args[1:], lambda m: m.has_uart()):
            if enable and not mod.has_uart():
                hint = ", use 'watch' for leds" if mod.has_leds() else ""
                raise Exception(f"'{mod}' has no terminals{hint}")
            for term in publishers(mod, "uart"):
                self.follow_terminal(term, enable)

    def watch_leds(self, leds, enable):
        self.led_states.pop(leds, None)
        if enable:
            self.led_states[leds] = read_led_states(leds)
        leds.on_led(self.show_led if enable else None)
        self.subscriptions = [(e, m) for e, m in self.subscriptions if e != "led" or m is not leds]
        if enable:
            self.subscriptions.append(("led", leds))

    def show_led(self, ev):
        states = self.led_states.setdefault(ev.leds, [])
        states += [None] * (ev.index + 1 - len(states))
        states[ev.index] = ev.state
        symbols = LED_SYMBOLS_UNICODE if use_unicode() else LED_SYMBOLS_ASCII
        bar = "".join(symbols[s] for s in states)
        self.print_event(f"{vcml.format_time(ev.time_ps)} {ev.leds} {bar}  ({ev.index} {'on' if ev.state else 'off'})")

    def follow_terminal(self, term, enable):
        self.flush_terminals()
        term.on_uart(self.show_terminal if enable else None)
        self.subscriptions = [(e, m) for e, m in self.subscriptions if e != "uart" or m is not term]
        if enable:
            self.subscriptions.append(("uart", term))

    def show_terminal(self, ev):
        line = self.term_lines.pop(ev.terminal, None)
        for c in ev.data:
            if line is None:
                line = (ev.time_ps, bytearray())
            if c == 0x0A:
                self.print_terminal_line(ev.terminal, *line)
                line = None
            elif c != 0x0D:
                line[1].append(c)
        if line is not None:
            self.term_lines[ev.terminal] = line

    def print_terminal_line(self, term, time_ps, data):
        self.print_event(f"{vcml.format_time(time_ps)} {term} | {escape_text(data)}")

    def flush_terminals(self):
        lines, self.term_lines = self.term_lines, {}
        for term, line in lines.items():
            if line[1]:
                self.print_terminal_line(term, *line)

    def handle_sessions(self, args):
        sessions = Session.local_sessions()
        if not sessions:
            print("no local sessions found")
        for s in sessions:
            print(f"{SESSION}{s.address()}{RESET} {DIM}({s.program}, pid {s.pid}){RESET}")

    def handle_help(self, args):
        for cmd in self.commands:
            h = self.commands[cmd]
            alias = [k for k, v in self.aliases.items() if str(v) == cmd]
            if alias:
                cmd = "|".join(alias) + "|" + cmd
            print(f"{WHITE + BOLD}{cmd:<16}{RESET}{h.desc}")

        if self.current and self.current.commands:
            print("\nModule commands")
            for cmd in self.current.commands:
                print(f"{BOLD + GREEN}{cmd.name:<16}{RESET}{cmd.desc}")


if __name__ == "__main__":
    app = Application()
    app.run()
