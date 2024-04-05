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
        if self.count == 0:
            return "<empty>"
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
