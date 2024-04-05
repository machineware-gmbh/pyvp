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

import xml.etree.ElementTree as ElementTree

from .attribute import Attribute
from .command import Command


class Module:
    def __init__(self, conn, parent, xmlnode):
        self.conn = conn
        self.parent = parent
        self.name = xmlnode.attrib["name"]
        self.kind = xmlnode.attrib["kind"]
        self.version = xmlnode.attrib["version"]
        self.modules = []
        self.attributes = []
        self.commands = []

        for subnode in xmlnode:
            if subnode.tag == "object":
                self.modules.append(Module(conn, self, subnode))
            elif subnode.tag == "attribute":
                self.attributes.append(Attribute(conn, self, subnode))
            elif subnode.tag == "command":
                self.commands.append(Command(self, conn, subnode))
            else:
                raise Exception("unexpected hierarchy node: " + str(subnode.tag))

    def __str__(self):
        return self.hierarchy_name()

    def hierarchy_name(self):
        if not isinstance(self.parent, Module):
            return self.name
        return self.parent.hierarchy_name() + "." + self.name

    def disconnect(self):
        for m in self.modules:
            m.disconnect()
        for a in self.attributes:
            a.disconnect()
        for c in self.commands:
            c.disconnect()

        self.conn = None
        self.parent = None

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
            for a in self.attributes:
                if a.name == path[0]:
                    return a
            return None

        m = self.find_module(path[:-1])
        return m.find_attribute(path[-1:]) if m else None

    def find_command(self, name):
        path = name if isinstance(name, list) else name.split(".")
        if len(path) == 1:
            for c in self.commands:
                if c.name == path[0]:
                    return c
            return None

        m = self.find_module(path[:-1])
        return m.find_command(path[-1:]) if m else None

    def dump(self):
        print(self.hierarchy_name() + " (" + self.kind + ")")
        for a in self.attributes:
            print("  " + a.name + ": " + a.type)
        for m in self.modules:
            m.dump()
