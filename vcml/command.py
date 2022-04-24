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

        cmd = "e," + self.parent.hierarchy_name() + "," + self.name
        if args:
            cmd = cmd + "," + ",".join(args)

        return self.conn.command(cmd)