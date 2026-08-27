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


class Application:
    def __init__(self):
        self.session: Session | None = None
        self.current: vcml.Module | None = None
        self.prevcmd = ["none"]

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
        else:
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
        print("connected to " + self.session.peer())

    def handle_disconnect(self, args):
        assert self.session
        print("disconnecting from session " + str(self.session))
        self.session.disconnect()
        self.current = None
        self.session = None

    def handle_quit(self, args):
        exit(int(args[1]) if len(args) > 1 else 0)

    def handle_kill(self, args):
        assert self.session
        print("terminating session " + str(self.session))
        self.session.kill()
        self.current = None
        self.session = None

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
        print(f"\nStopped by {stop_reason}")

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
            outputs.append(f"{MODULE}{m.name:<20}{RESET}")
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
