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


class Attribute:
    def __init__(self, conn, parent, xmlnode):
        self.conn = conn
        self.parent = parent
        self.name = str(xmlnode.attrib["name"])
        self.type = str(xmlnode.attrib["type"])
        self.count = int(xmlnode.attrib["count"])

    def __str__(self):
        return self.hierarchy_name()

    def hierarchy_name(self):
        return self.parent.hierarchy_name() + "." + self.name

    def get(self):
        val = self.conn.command("geta," + self.hierarchy_name())
        if len(val) != self.count:
            raise Exception("unexpected response to a command: " + str(val))
        if self.count == 1:
            return val[0]
        return val

    def set(self, val):
        return  # ToDo

    def disconnect(self):
        self.conn = None
        self.parent = None
