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


class Target:
    def __init__(self, conn, xmlnode):
        self._conn = conn
        self.name = xmlnode.text

    def __str__(self):
        return self.name
