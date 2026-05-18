# -*- coding: utf-8 -*-
"""
Kombinovaný Python Toolbox pro MADASPRU CAD Import.
Jeden nástroj spustí za sebou workflow Řešených území a workflow Výšek
a exportuje vše do jednoho společného datasetu.
"""

import arcpy
import os
import sys
import datetime
import shutil
import tempfile

# ──────────────────────────────────────────────────────────────────────────────
# Dynamické načtení kódu z dílčích .pyt souborů
# ──────────────────────────────────────────────────────────────────────────────
_current_dir = os.path.dirname(os.path.abspath(__file__))

_resene_path = os.path.join(_current_dir, "Prevodnik_CAD_GIS_ReseneUzemi.pyt")
_resene_globals = {}
with open(_resene_path, "r", encoding="utf-8") as _f:
    exec(_f.read(), _resene_globals)

_vysky_path = os.path.join(_current_dir, "Prevodnik_CAD_GIS_Vysky.pyt")
_vysky_globals = {}
with open(_vysky_path, "r", encoding="utf-8") as _f:
    exec(_f.read(), _vysky_globals)

# Vystavit třídy nástrojů (pro případ přímého importu)
ExportLayer = _resene_globals["ExportLayer"]
HeightRegulationImport = _vysky_globals["HeightRegulationImport"]

# ──────────────────────────────────────────────────────────────────────────────
# Toolbox
# ──────────────────────────────────────────────────────────────────────────────

class Toolbox(object):
    def __init__(self):
        self.label = "MADASPRU CAD Import"
        self.alias = "MADASPRU_CAD_Import"
        self.tools = [CombinedCADImport]


# ──────────────────────────────────────────────────────────────────────────────
# Kombinovaný nástroj
# ──────────────────────────────────────────────────────────────────────────────

class CombinedCADImport(object):
    """
    Kombinovaný import CAD → GIS.
    Spustí za sebou:
      1. Workflow Řešených území  (ExportLayer z ReseneUzemi.pyt)
      2. Workflow Výšek           (HeightRegulationImport z Vysky.pyt)
    Oba výstupy jdou do stejné GDB / Feature Datasetu.
    """

    def __init__(self):
        self.label = "Import CAD do GIS (Řešená území + Výšky)"
        self.alias = "combinedCADImport"
        self.canRunInBackground = False

    # ------------------------------------------------------------------
    # Parametry
    # ------------------------------------------------------------------
    def getParameterInfo(self):
        # 0 – Input CAD soubor
        p0 = arcpy.Parameter(
            displayName="Input CAD Soubor",
            name="input_cad",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
        )
        p0.filter.list = ["dwg", "dxf", "dgn"]

        # 1 – CAD vrstvy (multi-value, volitelné – vyplní se automaticky)
        p1 = arcpy.Parameter(
            displayName="CAD Vrstvy",
            name="cad_layers",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        p1.enabled = False

        # 2 – Output GDB
        p2 = arcpy.Parameter(
            displayName="Output Geodatabáze",
            name="output_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        p2.filter.list = ["Local Database"]
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            p2.value = aprx.defaultGeodatabase
        except Exception:
            try:
                fallback = r"C:\GIS_Data\Output.gdb"
                if arcpy.Exists(fallback):
                    p2.value = fallback
            except Exception:
                pass

        # 3 – Output Feature Dataset (volitelný)
        p3 = arcpy.Parameter(
            displayName="Output Feature Dataset (volitelný)",
            name="output_fd",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )

        # 4 – XY Tolerance
        p4 = arcpy.Parameter(
            displayName="XY Tolerance (m)",
            name="xy_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p4.value = 0.01

        # 5 – XY Resolution
        p5 = arcpy.Parameter(
            displayName="XY Resolution (m)",
            name="xy_resolution",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        p5.value = 0.001

        return [p0, p1, p2, p3, p4, p5]

    # ------------------------------------------------------------------
    # Automatické naplnění seznamu vrstev po výběru CAD souboru
    # ------------------------------------------------------------------
    def updateParameters(self, parameters):
        if not (parameters[0].altered and parameters[0].value):
            return

        cad_path = parameters[0].valueAsText
        original_ws = arcpy.env.workspace
        try:
            # Rozlišujeme vrstvy pro ReseneUzemi i pro Výšky
            resene_layers = {
                "101110_PL_Resene_uzemi": ["Polyline"],
                "200000_PL_Cast_uzemi":   ["Polyline", "Point"],
                "101111_BL_Resene_uzemi": ["Point"],
                "201110_PL_Ulicni_cara":  ["Polyline"],
                "202110_BL_Cast_uzemi_UP": ["Point"],
                "203110_BL_Cast_uzemi_SB": ["Point"],
                "204110_BL_Cast_uzemi_NB": ["Point"],
                "205110_BL_Cast_uzemi_XB": ["Point"],
                "302310_BL_VR_na_plochu":  ["Polyline"],
                "302311_PL_VR_na_plochu_rozhrani": ["Polyline"],
            }
            vysky_layers = {
                "302210_BL_VR_na_linii":        ["Polyline"],
                "302211_PL_VR_na_linii_rozhrani": ["Polyline"],
                "302110_BL_VR_na_bod":          ["Polyline"],
            }
            # SC vrstvy pro Výšky
            sc_prefix_filter = "3011"

            arcpy.env.workspace = cad_path
            all_available = []
            selected = []

            polyline_fc = None
            if arcpy.Exists("Polyline"):
                polyline_fc = "Polyline"
            elif arcpy.Exists(os.path.join(cad_path, "Polyline")):
                polyline_fc = os.path.join(cad_path, "Polyline")

            point_fc = None
            if arcpy.Exists("Point"):
                point_fc = "Point"
            elif arcpy.Exists(os.path.join(cad_path, "Point")):
                point_fc = os.path.join(cad_path, "Point")

            pl_layers = set()
            pt_layers = set()
            if polyline_fc:
                with arcpy.da.SearchCursor(polyline_fc, ["Layer"]) as cur:
                    for r in cur:
                        if r[0]:
                            pl_layers.add(r[0])
            if point_fc:
                with arcpy.da.SearchCursor(point_fc, ["Layer"]) as cur:
                    for r in cur:
                        if r[0]:
                            pt_layers.add(r[0])

            for lyr in sorted(pl_layers):
                disp = f"{lyr} (Polyline)"
                all_available.append(disp)
                in_resene = lyr in resene_layers and "Polyline" in resene_layers[lyr]
                in_vysky  = lyr in vysky_layers and "Polyline" in vysky_layers[lyr]
                is_sc     = lyr.startswith(sc_prefix_filter) and "_PL_SC_" in lyr
                if in_resene or in_vysky or is_sc:
                    selected.append(disp)

            for lyr in sorted(pt_layers):
                disp = f"{lyr} (Point)"
                all_available.append(disp)
                in_resene = lyr in resene_layers and "Point" in resene_layers[lyr]
                in_vysky  = lyr in vysky_layers and "Point" in vysky_layers[lyr]
                if in_resene or in_vysky:
                    selected.append(disp)

            parameters[1].filter.list = all_available
            parameters[1].values = selected if selected else all_available
            parameters[1].enabled = bool(all_available)

        except Exception as e:
            arcpy.AddWarning(f"[updateParameters] Chyba při načítání CAD vrstev: {e}")
        finally:
            arcpy.env.workspace = original_ws

    def updateMessages(self, parameters):
        return

    # ------------------------------------------------------------------
    # Spuštění
    # ------------------------------------------------------------------
    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True
        arcpy.env.workspace = None

        input_cad  = parameters[0].valueAsText
        sel_layers = parameters[1].values if parameters[1].values else []
        output_gdb = parameters[2].valueAsText
        fd_name    = parameters[3].valueAsText
        xy_tolerance  = parameters[4].value or 0.01
        xy_resolution = parameters[5].value or 0.001

        # Výchozí SR = S-JTSK / Krovak East North (EPSG 5514)
        output_sr = arcpy.SpatialReference(5514)

        # Připrav výstupní workspace (GDB nebo Feature Dataset)
        if fd_name:
            fd_path = os.path.join(output_gdb, fd_name)
            if not arcpy.Exists(fd_path):
                arcpy.AddMessage(f"▶️ Vytvářím Feature Dataset: {fd_name}")
                old_tol = arcpy.env.XYTolerance
                old_res = arcpy.env.XYResolution
                arcpy.env.XYTolerance  = f"{xy_tolerance} Meters"
                arcpy.env.XYResolution = f"{xy_resolution} Meters"
                try:
                    arcpy.management.CreateFeatureDataset(output_gdb, fd_name, output_sr)
                finally:
                    if old_tol: arcpy.env.XYTolerance  = old_tol
                    if old_res: arcpy.env.XYResolution = old_res
            output_workspace = fd_path
        else:
            output_workspace = output_gdb

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("KROK 1: IMPORT ŘEŠENÝCH ÚZEMÍ")
        arcpy.AddMessage("=" * 60)

        # ── KROK 1: Řešená území ──────────────────────────────────────
        resene_layers_sel = [
            lyr for lyr in sel_layers
            if not (
                " (Polyline)" in lyr and (
                    lyr.split(" (")[0].startswith("3011") and "_PL_SC_" in lyr.split(" (")[0]
                    or lyr.split(" (")[0] in (
                        "302210_BL_VR_na_linii",
                        "302211_PL_VR_na_linii_rozhrani",
                        "302110_BL_VR_na_bod",
                    )
                )
            )
        ]

        _ru_tool = _resene_globals["ExportLayer"]()

        # Sestav falešné parametry pro ExportLayer.execute()
        class _Param:
            def __init__(self, val):
                self.value = val
                self.valueAsText = str(val) if val is not None else None
                self.values = val if isinstance(val, list) else None

        ru_params = [
            _Param(input_cad),
            _Param(resene_layers_sel),
            _Param(output_gdb),
            _Param(fd_name),
            _Param(xy_tolerance),
            _Param(xy_resolution),
            _Param(output_sr),
            _Param(None),       # transformation
            _Param("Z"),        # out_prefix
        ]
        # valueAsText pro seznam vrstev
        ru_params[1].valueAsText = ";".join(resene_layers_sel) if resene_layers_sel else None

        try:
            _ru_tool.execute(ru_params, messages)
        except Exception as e_ru:
            arcpy.AddWarning(f"⚠️ Chyba při importu Řešených území: {e_ru}")

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("KROK 2: IMPORT VÝŠEK")
        arcpy.AddMessage("=" * 60)

        # ── KROK 2: Výšky ────────────────────────────────────────────
        # SC vrstvy + VR vrstvy
        vysky_layers_sel = [
            lyr for lyr in sel_layers
            if (
                (" (Polyline)" in lyr and (
                    lyr.split(" (")[0].startswith("3011") and "_PL_SC_" in lyr.split(" (")[0]
                    or lyr.split(" (")[0] in (
                        "302210_BL_VR_na_linii",
                        "302211_PL_VR_na_linii_rozhrani",
                        "302110_BL_VR_na_bod",
                    )
                ))
            )
        ]

        _vy_tool = _vysky_globals["HeightRegulationImport"]()

        vy_params = [
            _Param(input_cad),
            _Param(vysky_layers_sel),
            _Param(output_gdb),
            _Param(fd_name),
            _Param(xy_tolerance),
            _Param(xy_resolution),
            _Param(output_sr),
            _Param(None),       # transformation
            _Param("Z"),        # out_prefix
            _Param(0.001),      # split_radius
        ]
        vy_params[1].valueAsText = ";".join(vysky_layers_sel) if vysky_layers_sel else None
        vy_params[1].values = vysky_layers_sel

        try:
            _vy_tool.execute(vy_params, messages)
        except Exception as e_vy:
            arcpy.AddWarning(f"⚠️ Chyba při importu Výšek: {e_vy}")

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("✅ Kombinovaný import dokončen.")
        arcpy.AddMessage("=" * 60)

        # Zápis logu
        try:
            log_folder = os.path.dirname(output_gdb)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(log_folder, f"combined_import_{ts}.txt")
            with open(log_path, "w", encoding="utf-8") as lf:
                lf.write(f"Kombinovaný import - {ts}\n")
                lf.write("=" * 60 + "\n")
                for line in (_resene_globals.get("_log_buffer", []) + _vysky_globals.get("_log_buffer", [])):
                    lf.write(str(line) + "\n")
            arcpy.AddMessage(f"📄 Log uložen: {log_path}")
        except Exception as _le:
            arcpy.AddWarning(f"Log soubor nelze zapsat: {_le}")
