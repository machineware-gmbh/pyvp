#!/usr/bin/env python3

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

import os
import sys
import time
import termcolors
import vcml

from typing import List
from collections import namedtuple
from vcml import Session, Attribute, Command


class Application:
    def __init__(self):
        self.session = None
        self.current = None
        self.prevcmd = ["none"]

        Handler = namedtuple("Handler", "func needs_session desc")
        self.commands = {
            "connect": Handler(self.handle_connect, False,
                "connect to a local simulation on <port> or to a remote one " +
                "on <host>:<port>"),
            "disconnect": Handler(self.handle_disconnect, True,
                "disconnect from the current session without terminating it"),
            "quit": Handler(self.handle_quit, False,
                "disconnect from session and quit program"),
            "kill": Handler(self.handle_kill, True,
                "terminate current session"),
            "info": Handler(self.handle_info, True,
                "print information about the current session"),
            "step": Handler(self.handle_step, True,
                "advances simulation to the next discrete timestamp"),
            "run": Handler(self.handle_run, True,
                "continues simulation, use CTRL+C to interrupt"),
            "list": Handler(self.handle_list, True,
                "displays the module hierarchy onwards from current module"),
            "cd": Handler(self.handle_cd, True,
                "moves current module to <module>"),
            "exec": Handler(self.handle_exec, True,
                "executes the given <command> [args...]"),
            "read": Handler(self.handle_read, True,
                "reads the given <attribute>"),
            "help": Handler(self.handle_help, False, "prints this message"),
        }

        self.aliases = {
            "t": "connect",
            "d": "disconnect",
            "i": "info",
            "s": "step",
            "c": "run",
            "k": "kill",
            "q": "quit",
            "l": "list",
            "ls": "list",
            "x": "exec",
            "r": "read",
            "h": "help",
        }

        self.help = []
        for c in self.commands:
            alias = [k for k, v in self.aliases.items() if str(v) == c]
            self.help.append([c] + alias)

        if len(sys.argv) >= 2:
            self.execute(["connect"] + sys.argv[-1:])

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
            sys.stdout.write("{}[{:.9f}s]{}".format(
                termcolors.TIMESTAMP, self.session.time() / 1e9,
                termcolors.RESET))
            sys.stdout.write(" " + termcolors.SESSION +
                             str(self.session) + termcolors.RESET)
            if self.current:
                sys.stdout.write(" {}".format(
                    termcolors.MODULE + str(self.current) + termcolors.RESET))
            sys.stdout.write("\n")
        else:
            print("{}[ no session ]{}".format(termcolors.RED + termcolors.BOLD,
                                              termcolors.RESET))
        sys.stdout.write("> ")
        sys.stdout.flush()

    def run(self):
        while True:
            self.prompt()
            args = sys.stdin.readline().split()
            self.execute(args)

    def execute(self, args):
        if not args:
            args = self.prevcmd

        overlay_command = self.find_command(args[0])
        if overlay_command:
            args = ["exec"] + args
        else:
            overlay_attribute = self.find_attribute(args[0])
            if overlay_attribute:
                args = ["read"] + args

        command = self.aliases.get(args[0], args[0])
        handler = self.commands.get(command)

        try:
            if not handler:
                raise Exception(
                    "unknown command '{}', try 'help'".format(command))

            if not self.session and handler.needs_session:
                raise Exception("not connected, use 'connect [host]:<port>'")

            handler.func(args)
            self.prevcmd = args
        except Exception as err:
            print("{}{}{}".format(termcolors.RED, err, termcolors.RESET))

    def handle_connect(self, args):
        if len(args) != 2:
            raise Exception("usage: {} [host]:<port>".format(args[0]))

        if self.session:
            self.handle_disconnect(args)

        print("connecting to {}...".format(args[1]))
        self.session = Session(args[1])
        print("connected to " + self.session.peer())

    def handle_disconnect(self, args):
        print("disconnecting from session " + str(self.session))
        self.session.disconnect()
        self.current = None
        self.session = None

    def handle_quit(self, args):
        exit(int(args[1]) if len(args) > 1 else 0)

    def handle_kill(self, args):
        print("terminating session " + str(self.session))
        self.session.kill()
        self.current = None
        self.session = None

    def handle_step(self, args):
        self.session.step()

    def handle_run(self, args: List[str]):
        self.session.run()
        try:
            while self.session.running():
                time.sleep(0.1)
                sys.stdout.write("\033[1000D{}{:<16}{}{:.9f}s | {}".format(
                    termcolors.HIGHLIGHT, "Simulating...",
                    termcolors.RESET, self.session.time() / 1e9,
                    self.session.cycle()))
                sys.stdout.flush()
        except KeyboardInterrupt:
            self.session.stop()
        print(f"\nStopped by {self.session.reason()}")

    def handle_info(self, args):
        reports = {
            "Simulation Host": self.session.peer(),
            "VCML Version": self.session.vcml_version(),
            "SystemC Version": self.session.sysc_version(),
            "Simulation Time": "{:.9f}s".format(self.session.time() / 1e9),
            "Delta Cycle": "{}".format(self.session.cycle())
        }

        for r in reports:
            print("{}{:<16}{}{}{}{}".format(termcolors.BOLD + termcolors.WHITE,
                  r, termcolors.RESET, termcolors.WHITE, reports[r],
                  termcolors.RESET))

    def handle_list(self, args):
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
            outputs.append("{}{:<20}{}".format(
                termcolors.MODULE, m.name, termcolors.RESET))
        for c in cmds:
            outputs.append("{}{:<20}{}".format(
                termcolors.COMMAND, c.name, termcolors.RESET))
        for a in attr:
            outputs.append("{}{:<20}{}".format(
                termcolors.ATTRIBUTE, a.name, termcolors.RESET))

        for i, s in enumerate(outputs):
            print(s, end='')
            if i % 5 == 4:
                print("")
        print("")

    def handle_cd(self, args):
        if len(args) > 2:
            raise Exception("Usage: {} [module|..]".format(args[0]))

        if len(args) == 1:
            self.current = None
            return

        if args[1] == "..":
            if self.current != None:
                self.current = self.current.parent
            return

        m = self.find_module(args[1])
        if not m:
            raise Exception("no such module: {}".format(args[1]))
        self.current = m

    def handle_exec(self, args):
        if len(args) < 2:
            raise Exception("usage: {} <command> [args...]".format(args[0]))

        name = args[1]
        args = args[2:]
        cmd = self.find_command(name)
        if not cmd:
            raise Exception("no such command: {}".format(name))

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
                    raise Exception("no such attribute: {}".format(arg))
                attrs.append(a)

        for attr in attrs:
            val = attr.get()
            print("{}{:<16}{}{}".format(termcolors.BOLD + termcolors.WHITE,
                                        attr.name, termcolors.RESET, str(val)))

    def handle_help(self, args):
        for cmd in self.commands:
            h = self.commands[cmd]
            alias = [k for k, v in self.aliases.items() if str(v) == cmd]
            if alias:
                cmd = "|".join(alias) + "|" + cmd
            print("{}{:<16}{}{}".format(termcolors.WHITE + termcolors.BOLD,
                  cmd, termcolors.RESET, h.desc))

        if self.current and self.current.commands:
            print("\nModule commands")
            for cmd in self.current.commands:
                print("{}{:<16}{}{}".format(termcolors.WHITE + termcolors.BOLD,
                                            cmd.name, termcolors.RESET,
                                            cmd.desc))

        #if self.current and self.current.debug():
        #    print("\nDebug commands")
        #    print("{}{:<16}{}{}".format(termcolors.WHITE + termcolors.BOLD,
        #                                "todo", termcolors.RESET,
        #                                "add commands for breakpoints, etc."))

if __name__ == "__main__":
    app = Application()
    app.run()
