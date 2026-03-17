# -*- coding: utf-8 -*-
"""
Hlavní Python Toolbox pro MADASPRU CAD Import nástroje.
Tento toolbox kombinuje nástroje pro Řešená území a Výšky pod jednu kapotu.
"""

import sys
import os
import arcpy

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
HeightRegulationImport = vysky_globals['HeightRegulationImport']


class UnifiedCadImport(object):
    """Jeden sjednocený nástroj: spustí Řešené území i Výšky do stejného výstupu."""

    RESENE_DEFAULT_LAYERS = {
        "101110_PL_Resene_uzemi": {"Polyline"},
        "200000_PL_Cast_uzemi": {"Polyline", "Point"},
        "101111_BL_Resene_uzemi": {"Point"},
        "201110_PL_Ulicni_cara": {"Polyline"},
        "202110_BL_Cast_uzemi_UP": {"Point"},
        "203110_BL_Cast_uzemi_SB": {"Point"},
        "204110_BL_Cast_uzemi_NB": {"Point"},
        "205110_BL_Cast_uzemi_XB": {"Point"},
        "302310_BL_VR_na_plochu": {"Polyline"},
        "302311_PL_VR_na_plochu_rozhrani": {"Polyline"},
    }

    VYSKY_DEFAULT_LAYERS = {
        "302110_BL_VR_na_bod",
        "302210_BL_VR_na_linii",
        "302211_PL_VR_na_linii_rozhrani",
    }

    def __init__(self):
        self.label = "Import CAD do GIS"
        self.alias = "unifiedCadImport"
        self.canRunInBackground = False

    def _resolve_cad_path(self, cad_path):
        if not cad_path:
            return cad_path
        if os.path.isdir(cad_path):
            cad_candidates = []
            for file_name in os.listdir(cad_path):
                if file_name.lower().endswith((".dwg", ".dxf", ".dgn")):
                    cad_candidates.append(os.path.join(cad_path, file_name))
            if cad_candidates:
                return cad_candidates[0]
        return cad_path

    def _scan_cad_layer_display_names(self, cad_path):
        resolved_cad = self._resolve_cad_path(cad_path)
        if not resolved_cad:
            return [], []

        original_workspace = arcpy.env.workspace
        polyline_layers = set()
        point_layers = set()

        try:
            arcpy.env.workspace = resolved_cad

            polyline_fc = None
            if arcpy.Exists("Polyline"):
                polyline_fc = "Polyline"
            elif arcpy.Exists(os.path.join(resolved_cad, "Polyline")):
                polyline_fc = os.path.join(resolved_cad, "Polyline")

            point_fc = None
            if arcpy.Exists("Point"):
                point_fc = "Point"
            elif arcpy.Exists(os.path.join(resolved_cad, "Point")):
                point_fc = os.path.join(resolved_cad, "Point")

            if polyline_fc:
                with arcpy.da.SearchCursor(polyline_fc, ["Layer"]) as cursor:
                    for row in cursor:
                        if row[0]:
                            polyline_layers.add(row[0])

            if point_fc:
                with arcpy.da.SearchCursor(point_fc, ["Layer"]) as cursor:
                    for row in cursor:
                        if row[0]:
                            point_layers.add(row[0])

        finally:
            arcpy.env.workspace = original_workspace

        available = []

        # 1) Vrstvy pro Výšky (jen polyline, stejně jako ve standalone nástroji).
        for layer_name in sorted(polyline_layers):
            if layer_name in self.VYSKY_DEFAULT_LAYERS or (layer_name.startswith("3011") and "_PL_SC_" in layer_name):
                available.append(f"{layer_name} (Polyline)")

        # 2) Vrstvy pro Řešené území (jen explicitně podporované kombinace vrstva/geometrie).
        for layer_name in sorted(polyline_layers):
            if layer_name in self.RESENE_DEFAULT_LAYERS and "Polyline" in self.RESENE_DEFAULT_LAYERS[layer_name]:
                display_name = f"{layer_name} (Polyline)"
                if display_name not in available:
                    available.append(display_name)

        for layer_name in sorted(point_layers):
            if layer_name in self.RESENE_DEFAULT_LAYERS and "Point" in self.RESENE_DEFAULT_LAYERS[layer_name]:
                display_name = f"{layer_name} (Point)"
                if display_name not in available:
                    available.append(display_name)

        # V unified toolu se mají zobrazovat jen skutečně relevantní vrstvy.
        defaults = list(available)

        return available, defaults

    def _is_vysky_layer_display(self, display_name):
        if " (" not in display_name or not display_name.endswith(")"):
            return False
        layer_name = display_name.split(" (")[0]
        geometry_type = display_name.split(" (")[1].rstrip(")")
        if geometry_type != "Polyline":
            return False
        return layer_name in self.VYSKY_DEFAULT_LAYERS or (
            layer_name.startswith("3011") and "_PL_SC_" in layer_name
        )

    def _is_resene_layer_display(self, display_name):
        if " (" not in display_name or not display_name.endswith(")"):
            return False
        layer_name = display_name.split(" (")[0]
        geometry_type = display_name.split(" (")[1].rstrip(")")
        return (
            layer_name in self.RESENE_DEFAULT_LAYERS and
            geometry_type in self.RESENE_DEFAULT_LAYERS[layer_name]
        )

    def _split_layers_for_tools(self, selected_layers):
        resene_layers = []
        vysky_layers = []

        for display_name in selected_layers or []:
            if self._is_resene_layer_display(display_name):
                resene_layers.append(display_name)
            if self._is_vysky_layer_display(display_name):
                vysky_layers.append(display_name)

        return resene_layers, vysky_layers

    def getParameterInfo(self):
        param0 = arcpy.Parameter(
            displayName="Input CAD Soubor",
            name="input_cad",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        param0.filter.list = ["dwg", "dxf", "dgn"]

        param1 = arcpy.Parameter(
            displayName="CAD Vrstvy",
            name="cad_layers",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True
        )
        param1.enabled = True
        param1.filter.type = "ValueList"

        param2 = arcpy.Parameter(
            displayName="Output Geodatabáze",
            name="output_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )
        param2.filter.list = ["Local Database"]
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            param2.value = aprx.defaultGeodatabase
        except Exception:
            pass

        param3 = arcpy.Parameter(
            displayName="Output Feature Dataset",
            name="output_fd",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        param4 = arcpy.Parameter(
            displayName="XY Tolerance (m)",
            name="xy_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param4.value = 0.01

        param5 = arcpy.Parameter(
            displayName="XY Resolution (m)",
            name="xy_resolution",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param5.value = 0.001

        param6 = arcpy.Parameter(
            displayName="Output Souřadnicový Systém",
            name="output_sr",
            datatype="GPSpatialReference",
            parameterType="Optional",
            direction="Input"
        )

        return [param0, param1, param2, param3, param4, param5, param6]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and parameters[0].value:
            cad_file = parameters[0].valueAsText
            try:
                available_layers, default_layers = self._scan_cad_layer_display_names(cad_file)
                parameters[1].filter.list = available_layers
                parameters[1].enabled = True

                if not parameters[1].altered:
                    if default_layers:
                        parameters[1].values = default_layers
                        parameters[1].value = ";".join([f"'{layer}'" for layer in default_layers])
                    else:
                        parameters[1].values = available_layers
                        parameters[1].value = ";".join([f"'{layer}'" for layer in available_layers])

                if not available_layers:
                    arcpy.AddWarning("[UnifiedCadImport.updateParameters] V CAD nebyly nalezeny vrstvy Point/Polyline pro nabídku CAD Vrstvy.")

                if not parameters[6].altered:
                    desc = arcpy.Describe(self._resolve_cad_path(cad_file))
                    if hasattr(desc, "spatialReference") and desc.spatialReference and desc.spatialReference.name != "Unknown":
                        parameters[6].value = desc.spatialReference
                    else:
                        parameters[6].value = arcpy.SpatialReference(5514)
            except Exception as e:
                arcpy.AddWarning(f"[UnifiedCadImport.updateParameters] Chyba při načítání CAD: {e}")

        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True

        input_cad = parameters[0].valueAsText
        selected_layers = parameters[1].values if parameters[1].values else []
        output_gdb = parameters[2].valueAsText
        fd_name = parameters[3].valueAsText
        xy_tolerance = parameters[4].value if parameters[4].value is not None else 0.01
        xy_resolution = parameters[5].value if parameters[5].value is not None else 0.001
        output_sr = parameters[6].value if parameters[6].value else arcpy.SpatialReference(5514)
        transform_method = None
        out_prefix = "Z_"
        split_radius = 0.001

        if not selected_layers:
            _, selected_layers = self._scan_cad_layer_display_names(input_cad)

        resene_layers, vysky_layers = self._split_layers_for_tools(selected_layers)

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("SPOUŠTÍM SJEDNOCENÝ IMPORT: ŘEŠENÉ ÚZEMÍ + VÝŠKY")
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage(f"CAD soubor: {input_cad}")
        arcpy.AddMessage(f"Výstupní GDB: {output_gdb}")
        arcpy.AddMessage(f"Výstupní Feature Dataset: {fd_name if fd_name else '(none)'}")
        arcpy.AddMessage(f"Počet vybraných CAD vrstev: {len(selected_layers)}")
        arcpy.AddMessage(f"  - pro Řešené území: {len(resene_layers)}")
        arcpy.AddMessage(f"  - pro Výšky: {len(vysky_layers)}")

        # 1) Řešené území
        if resene_layers:
            arcpy.AddMessage("▶ Spouštím převodník: Řešené území")
            resene_tool = ExportLayer()
            resene_params = resene_tool.getParameterInfo()
            resene_params[0].value = input_cad
            resene_params[1].values = resene_layers
            resene_params[1].value = ";".join([f"'{layer}'" for layer in resene_layers])
            resene_params[2].value = output_gdb
            resene_params[3].value = fd_name
            resene_params[4].value = xy_tolerance
            resene_params[5].value = xy_resolution
            resene_params[6].value = output_sr
            resene_params[7].value = transform_method
            resene_params[8].value = out_prefix
            resene_tool.execute(resene_params, messages)
        else:
            arcpy.AddWarning("Převodník Řešené území přeskočen: nebyly vybrány žádné relevantní CAD vrstvy.")

        # 2) Výšky
        if vysky_layers:
            arcpy.AddMessage("▶ Spouštím převodník: Výšky")
            vysky_tool = HeightRegulationImport()
            vysky_params = vysky_tool.getParameterInfo()
            vysky_params[0].value = input_cad
            vysky_params[1].values = vysky_layers
            vysky_params[2].value = output_gdb
            vysky_params[3].value = fd_name
            vysky_params[4].value = xy_tolerance
            vysky_params[5].value = xy_resolution
            vysky_params[6].value = output_sr
            vysky_params[7].value = transform_method
            vysky_params[8].value = out_prefix
            vysky_params[9].value = split_radius
            vysky_tool.execute(vysky_params, messages)
        else:
            arcpy.AddWarning("Převodník Výšky přeskočen: nebyly vybrány žádné relevantní CAD vrstvy.")

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("SJEDNOCENÝ IMPORT DOKONČEN")
        arcpy.AddMessage("=" * 60)


class Toolbox(object):
    def __init__(self):
        """Definice toolboxu - hlavní kontejner pro všechny nástroje"""
        self.label = "MADASPRU CAD Import Tools"
        self.alias = "MADASPRU_CAD_Import"
        
        # Jednotný vstupní nástroj, který spustí oba převodníky do stejného datasetu.
        self.tools = [UnifiedCadImport]
