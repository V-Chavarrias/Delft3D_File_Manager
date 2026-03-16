# -*- coding: utf-8 -*-
def classFactory(iface):
    from .Delft3DFileManager import Delft3DFileManager
    return Delft3DFileManager(iface)