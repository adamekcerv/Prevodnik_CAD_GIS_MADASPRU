# -*- coding: utf-8 -*-
"""
Hlavní Python Toolbox pro MADASPRU CAD Import nástroje.
Tento toolbox kombinuje nástroje pro Řešená území a Výšky pod jednu kapotu.
"""

import sys
import os

# Získat cestu k aktuálnímu adresáři
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Načtení tříd nástrojů pomocí exec()
# ReseneUzemi
resene_path = os.path.join(current_dir, "Prevodnik_CAD_GIS_ReseneUzemi.pyt")
resene_globals = {}
with open(resene_path, 'r', encoding='utf-8') as f:
    exec(f.read(), resene_globals)
ExportLayer = resene_globals['ExportLayer']

# Vysky
vysky_path = os.path.join(current_dir, "Prevodnik_CAD_GIS_Vysky.pyt")
vysky_globals = {}
with open(vysky_path, 'r', encoding='utf-8') as f:
    exec(f.read(), vysky_globals)
SimpleCADImport = vysky_globals['SimpleCADImport']


class Toolbox(object):
    def __init__(self):
        """Definice toolboxu - hlavní kontejner pro všechny nástroje"""
        self.label = "MADASPRU CAD Import Tools"
        self.alias = "MADASPRU_CAD_Import"
        
        # Oba nástroje pod jednou střechou
        self.tools = [ExportLayer, SimpleCADImport]
