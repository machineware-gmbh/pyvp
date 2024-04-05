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
from typing import List

from .connection import Connection


class Command:
    def __init__(self, parent, conn: Connection, xmlnode: ElementTree):
        self.conn = conn
        self.parent = parent
        self.name : str = str(xmlnode.attrib["name"])
        self.argc : int = int(xmlnode.attrib["argc"])
        self.desc : str = str(xmlnode.attrib["desc"])

    def __str__(self):
        return self.hierarchy_name()

    def hierarchy_name(self) -> str:
        return self.parent.hierarchy_name() + "." + self.name

    def disconnect(self):
        self.conn = None
        self.parent = None

    def execute(self, args: List[str]):
        if len(args) < self.argc:
            raise Exception("need {} argument(s) for {}, have {}".format(
                self.argc, self.name, len(args)))

        cmd = "exec," + self.parent.hierarchy_name() + "," + self.name
        if args:
            cmd = cmd + "," + ",".join(args)

        return self.conn.command(cmd)
