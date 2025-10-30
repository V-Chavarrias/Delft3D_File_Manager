# -*- coding: utf-8 -*-
def classFactory(iface):
    from .WeirImporter import WeirImporter
    return WeirImporter(iface)