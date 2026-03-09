# -*- coding: utf-8 -*-
import arcpy
import os

# Defaultní vrstvy pro MADASPRU project
DEFAULT_LAYERS = [
    "302110_BL_VR_na_bod",
    "302210_BL_VR_na_linii",
    "302211_PL_VR_na_linii_rozhrani"
]

# Výškové atributy pro dissolve a přenos (VYSKOVA_REGULACE_SPOLECNE_ATRIBUTY)
HEIGHT_ATTRIBUTES = [
    "VYSKA_VB", "VYSKA_VB_I",
    "NP_MIN", "NP_MAX", "NPU_MAX",
    "RIMSA_MIN", "RIMSA_MAX",
    "VYSKA_MAX"
]

# Mapování čísla CAD vrstvy na kód domény DRUH_STAVEBNI_CARY
SC_DRUH_MAPPING = {
    "301110": "SCU",   # stavební čára uzavřená
    "301111": "SCPU",  # stavební čára polouzavřená
    "301112": "SCO",   # stavební čára otevřená
    "301113": "SCV",   # stavební čára volná
    "301114": "SC",    # stavební čára bez rozlišení
    "301115": "SCX",   # stavební čára jiná
}

def get_druh_sc_from_sc_type(sc_type):
    """Vrátí kód DRUH_SC na základě názvu SC_TYPE (číslo vrstvy je prefix)."""
    if not sc_type:
        return None
    for prefix, druh in SC_DRUH_MAPPING.items():
        if str(sc_type).startswith(prefix):
            return druh
    return None

def generate_unique_name(gdb_path, base_name):
    """Generuje unikátní název pro feature class v geodatabázi"""
    unique_name = base_name
    counter = 1
    
    original_workspace = arcpy.env.workspace
    
    try:
        while arcpy.Exists(os.path.join(gdb_path, unique_name)):
            arcpy.env.workspace = gdb_path
            datasets = arcpy.ListDatasets("", "Feature")
            name_exists = False
            
            for dataset in datasets or []:
                if arcpy.Exists(os.path.join(gdb_path, dataset, unique_name)):
                    name_exists = True
                    break
            
            if name_exists or arcpy.Exists(os.path.join(gdb_path, unique_name)):
                unique_name = f"{base_name}_{counter}"
                counter += 1
            else:
                break
    finally:
        arcpy.env.workspace = original_workspace
    
    return unique_name


def log_message(message, level="INFO"):
    """Helper pro logování s úrovněmi"""
    prefix = {
        "INFO": "ℹ️",
        "OK": "✅",
        "WARN": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
        "STEP": "▶️"
    }.get(level, "")
    
    arcpy.AddMessage(f"{prefix} {message}")



def sanitize_name(name):
    """Odstraní nepovolené znaky z názvu"""
    if not name:
        return "unknown"
    return "".join(c if c.isalnum() else "_" for c in str(name))


def get_feature_count(fc):
    """Bezpečné získání počtu prvků"""
    try:
        return int(arcpy.GetCount_management(fc)[0])
    except:
        return 0


def get_vr_attributes(vr_feature_class):
    """
    Získá POUZE relevantní atributy z VR bloků (výškové + dokumentační)
    Vyloučí CAD metadata (Entity, Handle, Layer, Color atd.)
    Returns: seznam názvů atributů
    """
    # Systémová pole
    excluded_fields = {
        "OBJECTID", "SHAPE", "SHAPE_LENGTH", "SHAPE_AREA", 
        "FID", "OID", "GLOBALID", "TARGET_FID", "SC_TYPE",
        "JOIN_FID", "JOIN_COUNT"
    }
    
    # CAD metadata - vyloučit (každý blok má unikátní hodnoty)
    cad_metadata_prefixes = {
        "ENTITY", "HANDLE", "LAYER", "LYR", "COLOR", "LINETYPE", 
        "LTSCALE", "ELEVATION", "THICKNESS", "LINEWT", "BLK",
        "ENT", "EXT", "DOC", "REF", "GLOBALWIDTH"
    }
    
    vr_attrs = []
    try:
        for field in arcpy.ListFields(vr_feature_class):
            field_upper = field.name.upper()
            
            # Skip systémová pole
            if field_upper in excluded_fields:
                continue
            if field_upper.startswith("SHAPE"):
                continue
            if field.type in ["Geometry", "OID"]:
                continue
            
            # Skip CAD metadata
            is_cad_metadata = False
            for prefix in cad_metadata_prefixes:
                if field_upper.startswith(prefix):
                    is_cad_metadata = True
                    break
            
            if not is_cad_metadata:
                vr_attrs.append(field.name)
    except:
        pass
    
    return vr_attrs


class Toolbox(object):
    def __init__(self):
        self.label = "MADASPRU CAD Import - Výšky v2"
        self.alias = "MADASPRU_Vysky_v2"
        self.tools = [HeightRegulationImport]


class HeightRegulationImport(object):
    def __init__(self):
        self.label = "Import CAD vrstev (Výšky)"
        self.alias = "heightRegulationImport"
        self.canRunInBackground = False

    def getParameterInfo(self):
        # Input CAD soubor
        param0 = arcpy.Parameter(
            displayName="Input CAD Soubor",
            name="input_cad",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        param0.filter.list = ["dwg", "dxf", "dgn"]

        # CAD vrstvy (automaticky předvybrané)
        param1 = arcpy.Parameter(
            displayName="CAD Vrstvy",
            name="cad_layers",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True
        )

        # Output geodatabáze
        param2 = arcpy.Parameter(
            displayName="Output Geodatabáze",
            name="output_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )
        param2.filter.list = ["Local Database"]
        
        # Nastavení výchozí hodnoty - aktuální projekt GDB nebo C:\GIS_Data\Output.gdb
        try:
            # Zkus použít Default.gdb z aktuálního projektu
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            param2.value = aprx.defaultGeodatabase
        except:
            # Fallback - pokud není projekt nebo selže
            try:
                default_path = r"C:\GIS_Data\Output.gdb"
                if arcpy.Exists(default_path):
                    param2.value = default_path
            except:
                pass

        # Output Feature Dataset
        param3 = arcpy.Parameter(
            displayName="Output Feature Dataset",
            name="output_fd",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        # XY Tolerance
        param4 = arcpy.Parameter(
            displayName="XY Tolerance (m)",
            name="xy_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param4.value = 0.01

        # XY Resolution
        param5 = arcpy.Parameter(
            displayName="XY Resolution (m)",
            name="xy_resolution",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param5.value = 0.001

        # Output souřadnicový systém
        param6 = arcpy.Parameter(
            displayName="Output Souřadnicový Systém",
            name="output_sr",
            datatype="GPSpatialReference",
            parameterType="Optional",
            direction="Input"
        )

        # Transformation
        param7 = arcpy.Parameter(
            displayName="Geographic Transformation",
            name="transformation",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        # Prefix
        param8 = arcpy.Parameter(
            displayName="Prefix jména výstupu",
            name="out_prefix",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        # Search radius pro split
        param9 = arcpy.Parameter(
            displayName="Search Radius pro Split (m)",
            name="split_radius",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param9.value = 0.001

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and parameters[0].value:
            cad_file = parameters[0].valueAsText
            
            try:
                arcpy.env.workspace = cad_file
                available_layers = []
                
                if arcpy.Exists("Polyline"):
                    with arcpy.da.SearchCursor("Polyline", ["Layer"]) as cursor:
                        layers = sorted(set([row[0] for row in cursor]))
                        for layer in layers:
                            # SC vrstvy + VR vrstvy
                            if layer.startswith("3011") and "_PL_SC_" in layer:
                                available_layers.append(f"{layer} (Polyline)")
                            elif layer in DEFAULT_LAYERS:
                                available_layers.append(f"{layer} (Polyline)")
                
                parameters[1].filter.list = available_layers
                parameters[1].values = available_layers
                parameters[1].enabled = True
                
                if not parameters[6].altered:
                    parameters[6].value = arcpy.SpatialReference(5514)
                    
            except Exception as e:
                arcpy.AddWarning(f"Chyba při načítání CAD: {e}")

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True
        
        # ============================================================
        # FÁZE 0: NAČTENÍ PARAMETRŮ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 0: NAČTENÍ PARAMETRŮ", "STEP")
        log_message("=" * 60, "INFO")
        
        input_cad = parameters[0].valueAsText
        selected_layers = parameters[1].values if parameters[1].values else []
        output_gdb = parameters[2].valueAsText
        
        fd_name = parameters[3].valueAsText
        xy_tolerance = parameters[4].value or 0.01
        xy_resolution = parameters[5].value or 0.001
        output_sr = parameters[6].value or arcpy.SpatialReference(5514)
        transform_method = parameters[7].valueAsText
        out_prefix = parameters[8].valueAsText or ""
        split_radius = parameters[9].value or 0.001
        
        log_message(f"CAD soubor: {input_cad}", "INFO")
        log_message(f"Output GDB: {output_gdb}", "INFO")
        log_message(f"Split radius: {split_radius}m", "INFO")
        log_message(f"Vybraných vrstev: {len(selected_layers)}", "INFO")

        # Vytvoření Feature Dataset pokud je zadán
        if fd_name:
            fd_path = os.path.join(output_gdb, fd_name)
            if not arcpy.Exists(fd_path):
                log_message(f"Vytvářím Feature Dataset: {fd_name}", "STEP")
                arcpy.CreateFeatureDataset_management(
                    out_dataset_path=output_gdb,
                    out_name=fd_name,
                    spatial_reference=output_sr
                )
                arcpy.env.XYTolerance = f"{xy_tolerance} Meters"
                arcpy.env.XYResolution = f"{xy_resolution} Meters"
            output_workspace = fd_path
        else:
            output_workspace = output_gdb

        # ============================================================
        # FÁZE 1: IMPORT A PŘÍPRAVA DAT
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 1: IMPORT A PŘÍPRAVA DAT", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_layers = []  # Seznam SC vrstev pro merge
        vr_rozhrani_layer = None  # 302211 - rozhraní
        vr_na_linii_layer = None  # 302210 - VR bloky na linii
        vr_na_bod_layer = None  # 302110 - VR bloky na bod
        exported_count = 0
        
        for layer_info in selected_layers:
            if " (Polyline)" in layer_info:
                layer_name = layer_info.replace(" (Polyline)", "")
                
                arcpy.env.workspace = input_cad
                
                field_delimited = arcpy.AddFieldDelimiters("Polyline", "Layer")
                where_clause = f"{field_delimited} = '{layer_name}'"
                
                if out_prefix:
                    base_name = f"{out_prefix}{layer_name}_LN"
                else:
                    base_name = f"PL_{layer_name}_LN"
                
                output_name = generate_unique_name(output_gdb, base_name)
                output_fc = os.path.join(output_workspace, output_name)
                
                try:
                    arcpy.FeatureClassToFeatureClass_conversion(
                        in_features="Polyline",
                        out_path=output_workspace,
                        out_name=output_name,
                        where_clause=where_clause
                    )
                    
                    if transform_method and not fd_name:
                        arcpy.Project_management(
                            in_dataset=output_fc,
                            out_dataset=output_fc + "_prj",
                            out_coor_system=output_sr,
                            transform_method=transform_method
                        )
                        arcpy.Delete_management(output_fc)
                        arcpy.Rename_management(output_fc + "_prj", output_name)
                    elif not fd_name:
                        arcpy.DefineProjection_management(output_fc, output_sr)
                    
                    count = get_feature_count(output_fc)
                    log_message(f"Importováno: {layer_name} ({count} prvků)", "OK")
                    exported_count += 1
                    
                    # Kategorizace vrstev
                    if layer_name.startswith("3011") and "_PL_SC_" in layer_name:
                        sc_layers.append(output_fc)
                    elif layer_name == "302211_PL_VR_na_linii_rozhrani":
                        vr_rozhrani_layer = output_fc
                    elif layer_name == "302110_BL_VR_na_bod":
                        vr_na_bod_layer = output_fc
                    elif layer_name == "302210_BL_VR_na_linii":
                        vr_na_linii_layer = output_fc
                    
                except Exception as e:
                    log_message(f"Chyba při exportu {layer_name}: {e}", "ERROR")

        log_message(f"Celkem importováno: {exported_count} vrstev", "OK")
        log_message(f"SC vrstev: {len(sc_layers)}", "DEBUG")
        log_message(f"VR rozhraní: {'Ano' if vr_rozhrani_layer else 'Ne'}", "DEBUG")
        log_message(f"VR na linii: {'Ano' if vr_na_linii_layer else 'Ne'}", "DEBUG")

        # Uložit mapování: layer_path -> type_name pro identifikaci po merge
        sc_type_mapping = {}  # {layer_path: type_name}
        for sc_layer in sc_layers:
            layer_basename = os.path.basename(sc_layer)
            # Extrahuj typ ze jména (např. "PL_301110_PL_SC_uzavrena_LN" -> "301110_PL_SC_uzavrena")
            if out_prefix:
                type_name = layer_basename.replace(out_prefix, "").replace("_LN", "")
            else:
                type_name = layer_basename.replace("PL_", "", 1).replace("_LN", "")
            sc_type_mapping[sc_layer] = type_name
            log_message(f"SC vrstva registrována: {type_name}", "DEBUG")

        # Merge SC vrstev + přidání pole SC_TYPE (aby bylo možné rozdělit zpět)
        merged_sc_all = None
        if len(sc_layers) >= 1:
            try:
                merged_sc_all = r"memory\sc_all_merged"
                
                # Přidat pole SC_TYPE do každé SC vrstvy PŘED mergem
                for sc_layer in sc_layers:
                    sc_type = sc_type_mapping[sc_layer]
                    
                    # Přidat pole pokud neexistuje
                    existing_fields = [f.name for f in arcpy.ListFields(sc_layer)]
                    if "SC_TYPE" not in existing_fields:
                        arcpy.management.AddField(sc_layer, "SC_TYPE", "TEXT", field_length=100)
                        log_message(f"Přidáno pole SC_TYPE do {os.path.basename(sc_layer)}", "DEBUG")
                    
                    # Nastavit hodnotu
                    updated_count = 0
                    with arcpy.da.UpdateCursor(sc_layer, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            row[0] = sc_type
                            cursor.updateRow(row)
                            updated_count += 1
                    log_message(f"SC_TYPE='{sc_type}' nastaveno pro {updated_count} prvků", "DEBUG")
                
                # Merge
                if len(sc_layers) >= 2:
                    arcpy.Merge_management(sc_layers, merged_sc_all)
                    log_message(f"Sloučeno {len(sc_layers)} SC vrstev (s polem SC_TYPE)", "OK")
                else:
                    arcpy.CopyFeatures_management(sc_layers[0], merged_sc_all)
                    log_message(f"Zkopírována 1 SC vrstva (s polem SC_TYPE)", "OK")
                
                sc_count = get_feature_count(merged_sc_all)
                log_message(f"Celkem SC linií: {sc_count}", "DEBUG")
                
                # DEBUG - kontrola SC_TYPE po merge
                fields = [f.name for f in arcpy.ListFields(merged_sc_all)]
                if "SC_TYPE" in fields:
                    sc_types_found = set()
                    with arcpy.da.SearchCursor(merged_sc_all, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            if row[0]:
                                sc_types_found.add(row[0])
                    log_message(f"SC_TYPE po merge: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
                else:
                    log_message("CHYBA: SC_TYPE pole CHYBÍ po merge!", "ERROR")
                
            except Exception as e:
                log_message(f"Chyba při merge SC vrstev: {e}", "ERROR")
                return

        # Zpracování VR bloků na linii - MultipartToSinglepart a filtrování kruhů
        vr_circles = None
        if vr_na_linii_layer and arcpy.Exists(vr_na_linii_layer):
            try:
                log_message("Zpracovávám VR bloky na linii...", "STEP")
                
                # Singlepart
                singlepart_temp = r"memory\vr_linii_singlepart"
                arcpy.management.MultipartToSinglepart(vr_na_linii_layer, singlepart_temp)
                
                # Filtrování uzavřených linií (kruhy)
                if out_prefix:
                    circles_name = f"{out_prefix}302210_VR_circles"
                else:
                    circles_name = "PL_302210_BL_VR_na_linii_circles"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                vr_circles = os.path.join(output_workspace, circles_name)
                
                arcpy.management.CreateFeatureclass(
                    out_path=output_workspace,
                    out_name=circles_name,
                    geometry_type="POLYLINE",
                    template=singlepart_temp,
                    spatial_reference=output_sr
                )
                
                field_names = [field.name for field in arcpy.ListFields(singlepart_temp) 
                              if field.type != "OID" and field.name.upper() != "OBJECTID"]
                
                circles_count = 0
                with arcpy.da.SearchCursor(singlepart_temp, ["SHAPE@"] + field_names) as search_cursor:
                    with arcpy.da.InsertCursor(vr_circles, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                log_message(f"Nalezeno {circles_count} VR bloků (uzavřených linií/kruhů)", "OK")
                
                arcpy.Delete_management(singlepart_temp)
                arcpy.Delete_management(vr_na_linii_layer)
                
            except Exception as e:
                log_message(f"Chyba při zpracování VR bloků: {e}", "ERROR")

        # ============================================================
        # FÁZE 2: VYTVOŘENÍ BODŮ ROZHRANÍ Z CAD
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 2: VYTVOŘENÍ BODŮ ROZHRANÍ Z CAD", "STEP")
        log_message("=" * 60, "INFO")
        
        rozhrani_body = None
        rozhrani_count_cad = 0
        
        if vr_rozhrani_layer and merged_sc_all and arcpy.Exists(vr_rozhrani_layer) and arcpy.Exists(merged_sc_all):
            try:
                # Intersect rozhraní se SC liniemi → body
                log_message("Hledám průsečíky rozhraní se SC liniemi...", "STEP")
                
                # Nejdřív SNAP rozhraní na SC linie (0.5m edge)
                rozhrani_for_intersect = vr_rozhrani_layer
                try:
                    log_message("Snap bodů rozhraní ke SC liniím (0.5m edge)...", "STEP")
                    # Export do memory pro editaci
                    rozhrani_snap_tm = r"memory\rozhrani_lines_snap"
                    arcpy.conversion.ExportFeatures(vr_rozhrani_layer, rozhrani_snap_tm)
                    
                    # Snap 
                    snap_env = [[merged_sc_all, "EDGE", "0.5 Meters"]]
                    arcpy.edit.Snap(rozhrani_snap_tm, snap_env)
                    
                    rozhrani_for_intersect = rozhrani_snap_tm
                    log_message("Snap rozhraní dokončen", "DEBUG")
                except Exception as e:
                    log_message(f"Snap rozhraní selhal, použiji původní: {e}", "WARN")

                arcpy.analysis.PairwiseIntersect(
                    in_features=[rozhrani_for_intersect, merged_sc_all],
                    out_feature_class=r"memory\rozhrani_body_multipart",
                    join_attributes="NO_FID",
                    cluster_tolerance=None,
                    output_type="POINT"
                )
                
                # Multipart to Singlepart
                arcpy.management.MultipartToSinglepart(
                    in_features=r"memory\rozhrani_body_multipart",
                    out_feature_class=r"memory\rozhrani_body_cad"
                )
                
                rozhrani_body = r"memory\rozhrani_body_cad"
                rozhrani_count_cad = get_feature_count(rozhrani_body)
                
                log_message(f"Nalezeno {rozhrani_count_cad} bodů rozhraní z CAD", "OK")
                
                # Snap bodů rozhraní ke SC liniím (30cm edge snap)
                log_message("Snap bodů rozhraní ke SC liniím (30cm edge)...", "STEP")
                try:
                    # Snap settings: [[snap_environment, snap_type, distance]]
                    snap_env = [[merged_sc_all, "EDGE", "0.3 Meters"]]
                    arcpy.edit.Snap(rozhrani_body, snap_env)
                    log_message("Snap dokončen", "OK")
                except Exception as snap_error:
                    log_message(f"Snap selhal (pokračuji bez snap): {snap_error}", "WARN")
                
                arcpy.Delete_management(r"memory\rozhrani_body_multipart")
                
            except Exception as e:
                log_message(f"Chyba při vytváření bodů rozhraní: {e}", "ERROR")
        else:
            log_message("VR rozhraní vrstva nebyla nalezena - přeskakuji", "WARN")

        # ============================================================
        # FÁZE 3: PRVNÍ ŘEZÁNÍ SC PODLE CAD ROZHRANÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 3: PRVNÍ ŘEZÁNÍ SC PODLE CAD ROZHRANÍ", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_split_cad = None
        
        if rozhrani_body and rozhrani_count_cad > 0:
            try:
                log_message(f"Řežu SC linie v {rozhrani_count_cad} místech rozhraní...", "STEP")
                
                # Zvýšený search_radius na 30cm pro zachycení blízkých rozhraní
                arcpy.management.SplitLineAtPoint(
                    in_features=merged_sc_all,
                    point_features=rozhrani_body,
                    out_feature_class=r"memory\sc_split_cad",
                    search_radius="0.3 Meters"
                )
                
                sc_split_cad = r"memory\sc_split_cad"
                split_count = get_feature_count(sc_split_cad)
                
                log_message(f"SC rozděleny na {split_count} segmentů", "OK")
                
            except Exception as e:
                log_message(f"Chyba při řezání SC: {e}", "ERROR")
                sc_split_cad = merged_sc_all  # Fallback na původní
        else:
            log_message("Žádná CAD rozhraní - SC zůstávají nerozdělené", "WARN")
            sc_split_cad = merged_sc_all

        # ============================================================
        # FÁZE 4: PŘIPOJENÍ VR BLOKŮ K SEGMENTŮM
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 4: PŘIPOJENÍ VR BLOKŮ K SEGMENTŮM", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_with_vr = None
        
        if vr_circles and sc_split_cad and arcpy.Exists(vr_circles):
            try:
                log_message("Připojuji VR bloky k SC segmentům (SpatialJoin)...", "STEP")
                
                arcpy.analysis.SpatialJoin(
                    target_features=sc_split_cad,
                    join_features=vr_circles,
                    out_feature_class=r"memory\sc_with_vr",
                    join_operation="JOIN_ONE_TO_MANY",
                    join_type="KEEP_ALL",
                    match_option="INTERSECT",
                    search_radius=None
                )
                
                sc_with_vr = r"memory\sc_with_vr"
                joined_count = get_feature_count(sc_with_vr)
                
                log_message(f"Spatial join dokončen: {joined_count} záznamů", "OK")
                
                # Debug - kolik má připojené VR
                with arcpy.da.SearchCursor(sc_with_vr, ["Join_Count"]) as cursor:
                    with_vr = sum(1 for row in cursor if row[0] and row[0] > 0)
                log_message(f"Segmentů s připojeným VR blokem: {with_vr}", "DEBUG")
                
            except Exception as e:
                log_message(f"Chyba při SpatialJoin: {e}", "ERROR")
                sc_with_vr = sc_split_cad
        else:
            log_message("VR bloky nebyly nalezeny - pokračuji bez připojení výšek", "WARN")
            sc_with_vr = sc_split_cad

        # ============================================================
        # FÁZE 5: DOGENEROVÁNÍ CHYBĚJÍCÍCH ROZHRANÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 5: DOGENEROVÁNÍ CHYBĚJÍCÍCH ROZHRANÍ", "STEP")
        log_message("=" * 60, "INFO")
        
        rozhrani_body_all = rozhrani_body  # Začneme s CAD rozhraními
        rozhrani_all = rozhrani_body  # Alias pro FÁZE 8
        
        if sc_with_vr and vr_circles:
            try:
                # Dynamicky získej VŠECHNY atributy z VR bloků
                vr_attributes = get_vr_attributes(vr_circles)
                log_message(f"VR atributy z bloků: {', '.join(vr_attributes) if vr_attributes else 'žádné'}", "DEBUG")
                
                # Zjisti, které z VR atributů jsou dostupné v sc_with_vr
                available_height_attrs = []
                fields = [f.name for f in arcpy.ListFields(sc_with_vr)]
                for attr in vr_attributes:
                    if attr in fields:
                        available_height_attrs.append(attr)
                
                log_message(f"Dostupné výškové atributy v SC: {', '.join(available_height_attrs)}", "DEBUG")
                
                if available_height_attrs:
                    # Dissolve podle VŠECH výškových atributů
                    log_message("Dissolve podle všech výškových atributů...", "STEP")
                    
                    # Vytvoř statistiky UNIQUE pro každý atribut
                    stats_fields = ";".join([f"{attr} UNIQUE" for attr in available_height_attrs])
                    
                    arcpy.management.Dissolve(
                        in_features=sc_with_vr,
                        out_feature_class=r"memory\sc_dissolve",
                        dissolve_field=available_height_attrs,
                        statistics_fields=stats_fields,
                        multi_part="SINGLE_PART",
                        unsplit_lines="DISSOLVE_LINES"
                    )
                    
                    dissolve_count = get_feature_count(r"memory\sc_dissolve")
                    log_message(f"Po dissolve: {dissolve_count} spojených segmentů", "DEBUG")
                    
                    # Vyber pouze ty s určenou výškou (alespoň jeden atribut není NULL)
                    where_parts = []
                    for attr in available_height_attrs:
                        where_parts.append(f"{attr} IS NOT NULL")
                    where_clause = " OR ".join(where_parts)
                    
                    arcpy.management.SelectLayerByAttribute(
                        in_layer_or_view=r"memory\sc_dissolve",
                        selection_type="NEW_SELECTION",
                        where_clause=where_clause
                    )
                    
                    selected_count = get_feature_count(r"memory\sc_dissolve")
                    log_message(f"Segmentů s výškou: {selected_count}", "DEBUG")
                    
                    if selected_count > 0:
                        # Koncové body těchto segmentů
                        arcpy.management.FeatureVerticesToPoints(
                            in_features=r"memory\sc_dissolve",
                            out_feature_class=r"memory\dissolve_vertices",
                            point_location="BOTH_ENDS"
                        )
                        
                        vertices_count = get_feature_count(r"memory\dissolve_vertices")
                        log_message(f"Koncových bodů: {vertices_count}", "DEBUG")
                        
                        # Najdi body které se překrývají (= rozhraní mezi různými typy)
                        arcpy.analysis.Intersect(
                            in_features=r"memory\dissolve_vertices",
                            out_feature_class=r"memory\overlapping_points",
                            join_attributes="ONLY_FID",
                            output_type="POINT"
                        )
                        
                        overlap_count = get_feature_count(r"memory\overlapping_points")
                        log_message(f"Překrývajících se bodů: {overlap_count}", "DEBUG")
                        
                        if overlap_count > 0:
                            # Dissolve překrývajících bodů do jednoho
                            arcpy.management.Dissolve(
                                in_features=r"memory\overlapping_points",
                                out_feature_class=r"memory\generated_rozhrani",
                                dissolve_field=None,
                                multi_part="SINGLE_PART"
                            )
                            
                            generated_count = get_feature_count(r"memory\generated_rozhrani")
                            log_message(f"Dogenerováno {generated_count} chybějících rozhraní", "OK")

                            # Export dogenerovaných rozhraní pro kontrolu
                            # Snap dogenerovaných rozhraní ke SC liniím
                            if merged_sc_all and arcpy.Exists(merged_sc_all):
                                log_message("Snap dogenerovaných rozhraní ke SC liniím (30cm edge)...", "STEP")
                                try:
                                    snap_env = [[merged_sc_all, "EDGE", "0.3 Meters"]]
                                    arcpy.edit.Snap(r"memory\generated_rozhrani", snap_env)
                                    log_message("Snap dokončen", "OK")
                                except Exception as snap_error:
                                    log_message(f"Snap selhal (pokračuji bez snap): {snap_error}", "WARN")
                            
                            # Merge CAD rozhraní + vygenerovaná
                            if rozhrani_body and arcpy.Exists(rozhrani_body):
                                arcpy.management.Merge(
                                    inputs=[rozhrani_body, r"memory\generated_rozhrani"],
                                    output=r"memory\rozhrani_all"
                                )
                            else:
                                arcpy.CopyFeatures_management(
                                    r"memory\generated_rozhrani",
                                    r"memory\rozhrani_all"
                                )
                            
                            rozhrani_body_all = r"memory\rozhrani_all"
                            rozhrani_all = rozhrani_body_all  # Alias pro FÁZE 8
                            total_rozhrani = get_feature_count(rozhrani_body_all)
                            log_message(f"Celkem rozhraní: {total_rozhrani}", "OK")
                            
                            # Cleanup
                            arcpy.Delete_management(r"memory\overlapping_points")
                            arcpy.Delete_management(r"memory\generated_rozhrani")
                        else:
                            log_message("Žádná dodatečná rozhraní nebyla potřeba", "INFO")
                        
                        arcpy.Delete_management(r"memory\dissolve_vertices")
                    
                    # Clear selection
                    arcpy.management.SelectLayerByAttribute(
                        in_layer_or_view=r"memory\sc_dissolve",
                        selection_type="CLEAR_SELECTION"
                    )
                    arcpy.Delete_management(r"memory\sc_dissolve")
                    
                else:
                    log_message("Žádné výškové atributy nebyly nalezeny", "WARN")
                    
            except Exception as e:
                log_message(f"Chyba při generování rozhraní: {e}", "ERROR")

        # ============================================================
        # FÁZE 6: FINÁLNÍ ŘEZÁNÍ VŠEMI ROZHRANÍMI
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 6: FINÁLNÍ ŘEZÁNÍ VŠEMI ROZHRANÍMI", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_final_split = None
        
        try:
            # Dissolve původních SC (čistá geometrie) - ZACHOVAT SC_TYPE
            log_message("Dissolve původních SC linií...", "STEP")
            
            arcpy.management.Dissolve(
                in_features=merged_sc_all,
                out_feature_class=r"memory\sc_dissolve_clean",
                dissolve_field="SC_TYPE",  # Zachovat typ SC
                multi_part="SINGLE_PART",
                unsplit_lines="DISSOLVE_LINES" 
            )
            
            clean_count = get_feature_count(r"memory\sc_dissolve_clean")
            log_message(f"Čistých spojených SC: {clean_count}", "DEBUG")
            
            # DEBUG - kontrola SC_TYPE po dissolve
            fields = [f.name for f in arcpy.ListFields(r"memory\sc_dissolve_clean")]
            if "SC_TYPE" in fields:
                sc_types_found = set()
                with arcpy.da.SearchCursor(r"memory\sc_dissolve_clean", ["SC_TYPE"]) as cursor:
                    for row in cursor:
                        if row[0]:
                            sc_types_found.add(row[0])
                log_message(f"SC_TYPE po dissolve: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
            else:
                log_message("VAROVÁNÍ: SC_TYPE pole CHYBÍ po dissolve!", "WARN")
            
            # Finální split všemi rozhraními
            if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
                rozhrani_total = get_feature_count(rozhrani_body_all)
                log_message(f"Řežu SC linie v {rozhrani_total} místech rozhraní...", "STEP")
                
                # Zvýšený search_radius na 30cm pro zachycení blízkých rozhraní
                arcpy.management.SplitLineAtPoint(
                    in_features=r"memory\sc_dissolve_clean",
                    point_features=rozhrani_body_all,
                    out_feature_class=r"memory\sc_final_split",
                    search_radius="0.3 Meters"
                )
                
                sc_final_split = r"memory\sc_final_split"
            else:
                log_message("Žádná rozhraní - používám dissolve výstup", "WARN")
                sc_final_split = r"memory\sc_dissolve_clean"
            
            final_count = get_feature_count(sc_final_split)
            log_message(f"Finální počet segmentů po split: {final_count}", "OK")
            
            # DEBUG - kontrola SC_TYPE po split
            fields = [f.name for f in arcpy.ListFields(sc_final_split)]
            if "SC_TYPE" in fields:
                sc_types_found = set()
                with arcpy.da.SearchCursor(sc_final_split, ["SC_TYPE"]) as cursor:
                    for row in cursor:
                        if row[0]:
                            sc_types_found.add(row[0])
                log_message(f"SC_TYPE po split: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
            else:
                log_message("VAROVÁNÍ: SC_TYPE pole CHYBÍ po split!", "WARN")
            
        except Exception as e:
            log_message(f"Chyba při finálním split: {e}", "ERROR")
            sc_final_split = merged_sc_all

        # ============================================================
        # FÁZE 7: ČIŠTĚNÍ FALEŠNÝCH ROZHRANÍ (podle notebooku)
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 7: ČIŠTĚNÍ FALEŠNÝCH ROZHRANÍ", "STEP")
        log_message("=" * 60, "INFO")
        
        # Logika z notebooku:
        # 1. Najdi koncové body SC segmentů
        # 2. Vyber ty, které NEKOLIDUJÍ s rozhraními (falešné řezy)
        # 3. Spoj segmenty, které mají tyto falešné řezy
        
        sc_cleaned = sc_final_split
        
        try:
            if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
                log_message("Detekuji falešná rozhraní (koncové body mimo skutečná rozhraní)...", "STEP")
                
                # 1. Extrahuj všechny koncové body SC segmentů
                arcpy.management.FeatureVerticesToPoints(
                    in_features=sc_final_split,
                    out_feature_class=r"memory\sc_split_endpoints",
                    point_location="BOTH_ENDS"
                )
                
                endpoints_count = get_feature_count(r"memory\sc_split_endpoints")
                log_message(f"Nalezeno {endpoints_count} koncových bodů", "DEBUG")
                
                # 2. Vyber body, které NEKOLIDUJÍ s rozhraními (= falešné řezy)
                arcpy.management.MakeFeatureLayer(r"memory\sc_split_endpoints", "endpoints_lyr")
                
                arcpy.management.SelectLayerByLocation(
                    in_layer="endpoints_lyr",
                    overlap_type="INTERSECT",
                    select_features=rozhrani_body_all,
                    search_distance="0.35 Meters",  # Trochu větší než split radius
                    selection_type="NEW_SELECTION",
                    invert_spatial_relationship="INVERT"
                )
                
                false_endpoints_count = int(arcpy.GetCount_management("endpoints_lyr")[0])
                log_message(f"Falešných koncových bodů (mimo rozhraní): {false_endpoints_count}", "DEBUG")
                
                if false_endpoints_count > 0:
                    arcpy.conversion.ExportFeatures(
                        in_features="endpoints_lyr",
                        out_features=r"memory\false_endpoints"
                    )
                    
                    # Export falešných bodů pro kontrolu - DISABLED FOR FINAL CLEANUP
                    # try:
                    #     if out_prefix:
                    #         false_name = f"{out_prefix}Rozhrani_falesne"
                    #     else:
                    #         false_name = "Z_Rozhrani_falesne"
                    #     
                    #     false_name = generate_unique_name(output_gdb, false_name)
                    #     false_output = os.path.join(output_workspace, false_name)
                    #     
                    #     arcpy.CopyFeatures_management(r"memory\false_endpoints", false_output)
                    #     log_message(f"Export falešných rozhraní (merged back): {false_name}", "DEBUG")
                    # except Exception as e:
                    #     log_message(f"Chyba při exportu falešných rozhraní: {e}", "WARN")

                    
                    # 3. Vyber SC segmenty, které se dotýkají falešných bodů
                    arcpy.management.MakeFeatureLayer(sc_final_split, "sc_split_lyr")
                    
                    arcpy.management.SelectLayerByLocation(
                        in_layer="sc_split_lyr",
                        overlap_type="INTERSECT",
                        select_features=r"memory\false_endpoints",
                        search_distance=None,
                        selection_type="NEW_SELECTION",
                        invert_spatial_relationship="NOT_INVERT"
                    )
                    
                    segments_to_merge = int(arcpy.GetCount_management("sc_split_lyr")[0])
                    log_message(f"Segmentů s falešnými rozhraními: {segments_to_merge}", "DEBUG")
                    
                    if segments_to_merge > 0:
                        # 4. Spoj tyto segmenty (dissolve podle SC_TYPE - aby se nespojily různé typy)
                        arcpy.conversion.ExportFeatures(
                            in_features="sc_split_lyr",
                            out_features=r"memory\segments_to_merge"
                        )
                        
                        # Dissolve podle SC_TYPE (spojí jen segmenty stejného typu)
                        dissolve_fields = ["SC_TYPE"] if "SC_TYPE" in [f.name for f in arcpy.ListFields(r"memory\segments_to_merge")] else []
                        
                        arcpy.management.Dissolve(
                            in_features=r"memory\segments_to_merge",
                            out_feature_class=r"memory\segments_merged",
                            dissolve_field=dissolve_fields,
                            statistics_fields=None,
                            multi_part="SINGLE_PART",
                            unsplit_lines="DISSOLVE_LINES"
                        )
                        
                        merged_count = get_feature_count(r"memory\segments_merged")
                        log_message(f"Po spojení falešných řezů: {merged_count} segmentů", "DEBUG")
                        
                        # 5. Najdi původní segmenty, které leží WITHIN spojených (= budou smazány)
                        arcpy.management.SelectLayerByLocation(
                            in_layer="sc_split_lyr",
                            overlap_type="WITHIN",
                            select_features=r"memory\segments_merged",
                            search_distance=None,
                            selection_type="NEW_SELECTION",
                            invert_spatial_relationship="NOT_INVERT"
                        )
                        
                        segments_to_delete = int(arcpy.GetCount_management("sc_split_lyr")[0])
                        log_message(f"Mazání {segments_to_delete} původních segmentů...", "DEBUG")
                        
                        # 6. Smazání původních rozdělených segmentů
                        if segments_to_delete > 0:
                            arcpy.management.DeleteRows("sc_split_lyr")
                        
                        # 7. Merge spojených segmentů zpět do sc_final_split
                        arcpy.management.Append(
                            inputs=r"memory\segments_merged",
                            target=sc_final_split,
                            schema_type="NO_TEST"
                        )
                        
                        final_cleaned_count = get_feature_count(sc_final_split)
                        log_message(f"Po čištění falešných rozhraní: {final_cleaned_count} segmentů", "OK")
                        log_message(f"Odstraněno {segments_to_delete - merged_count} falešných řezů", "OK")
                    else:
                        log_message("Žádné segmenty s falešnými rozhraními nenalezeny", "DEBUG")
                else:
                    log_message("Všechny koncové body odpovídají skutečným rozhraním", "OK")
                
                sc_cleaned = sc_final_split
                
            else:
                log_message("Žádná rozhraní - přeskakuji čištění", "DEBUG")
                sc_cleaned = sc_final_split
        
        except Exception as e:
            log_message(f"Chyba při čištění falešných rozhraní: {e}", "WARN")
            log_message("Pokračuji s nečištěnými segmenty", "WARN")
            sc_cleaned = sc_final_split
        
        # DEBUG - kontrola SC_TYPE
        fields = [f.name for f in arcpy.ListFields(sc_cleaned)]
        if "SC_TYPE" in fields:
            sc_types_found = set()
            with arcpy.da.SearchCursor(sc_cleaned, ["SC_TYPE"]) as cursor:
                for row in cursor:
                    if row[0]:
                        sc_types_found.add(row[0])
            log_message(f"SC_TYPE zachováno: {len(sc_types_found)} typů", "DEBUG")
        
        # ============================================================
        # FÁZE 8: FINÁLNÍ PŘIPOJENÍ ATRIBUTŮ (podle notebooku)
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 8: FINÁLNÍ PŘIPOJENÍ ATRIBUTŮ", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_final_with_vr = None
        
        if vr_circles and arcpy.Exists(vr_circles) and sc_cleaned:
            try:
                # Finální SpatialJoin s VR bloky (podle notebooku)
                log_message("Finální SpatialJoin s VR bloky...", "STEP")
                
                arcpy.analysis.SpatialJoin(
                    target_features=sc_cleaned,
                    join_features=vr_circles,
                    out_feature_class=r"memory\sc_final_sj",
                    join_operation="JOIN_ONE_TO_MANY",
                    join_type="KEEP_ALL",
                    match_option="INTERSECT"
                )
                
                # OPRAVA: Přenést atributy z napojovaných polí (s suffixem _1) do hlavních polí
                # Protože target features už ta pole mají (ale prázdná), ArcGIS je při joinu přejmenuje (např. RIMSA_MAX_1)
                # Musíme je zkopírovat zpět.
                
                # Zjisti skutečné názvy polí v toolu
                sj_fields = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                
                # Seznam atributů k opravě
                attrs_to_fix = [
                    "OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO",
                    "NP_MAX", "NUP_MAX", "RIMSA_MAX", 
                    "VYSKA_VB", "VYSKA_VB_I", "DOK_NAZEV"
                ]
                
                # log_message("Opravuji hodnoty atributů po Spatial Join...", "DEBUG")
                
                for attr in attrs_to_fix:
                    # Hledáme varianty s suffixem (např. RIMSA_MAX_1)
                    source_field = None
                    for f in sj_fields:
                        if f == f"{attr}_1" or f == f"{attr}_12": # _12 může vzniknout pokud už tam _1 bylo
                            source_field = f
                            break
                    
                    if source_field and attr in sj_fields:
                        # Přenést data z source_field do attr
                        # log_message(f"  - Přenáším {source_field} -> {attr}", "DEBUG")
                        with arcpy.da.UpdateCursor(r"memory\sc_final_sj", [attr, source_field]) as cursor:
                            for row in cursor:
                                # Pokud je hlavní pole prázdné a vedlejší má hodnotu -> update
                                if row[0] is None and row[1] is not None:
                                    row[0] = row[1]
                                    cursor.updateRow(row)
                
                sj_count = get_feature_count(r"memory\sc_final_sj")
                log_message(f"SpatialJoin výsledek: {sj_count} záznamů", "DEBUG")
                
                # DEBUG - kontrola SC_TYPE po SpatialJoin
                fields_sj = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                if "SC_TYPE" in fields_sj:
                    log_message("SC_TYPE nalezeno po SpatialJoin", "DEBUG")
                else:
                    log_message("VAROVÁNÍ: SC_TYPE CHYBÍ po SpatialJoin!", "WARN")
                
                # ============================================================
                # PROPAGACE ATRIBUTŮ MEZI ROZHRANÍMI
                # ============================================================
                # ============================================================
                # PROPAGACE ATRIBUTŮ (SERIAL & PARALLEL)
                # ============================================================
                # Cíl: Přenést atributy přes rozdělené segmenty (i různých typů),
                # POKUD mezi nimi není rozhraní.
                
                log_message("Spouštím chytrou propagaci atributů (Respektuje rozhraní)...", "STEP")
                
                if vr_circles and arcpy.Exists(vr_circles):
                    vr_attributes = get_vr_attributes(vr_circles)
                else:
                    vr_attributes = []
                
                fields = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                available_height_attrs = [attr for attr in vr_attributes if attr in fields]
                
                if available_height_attrs:
                    # 1. Vytvoř buffer kolem rozhraní (to jsou bariéry)
                    # Používáme POUZE rozhrani_body (z CADu), nikoliv rozhrani_body_all (které obsahuje i dogenerované)
                    # Chceme, aby se atributy přelily přes dogenerovaná rozhraní (která vznikla jen proto, že tam chyběla data),
                    # ale aby se zastavily o skutečná CAD rozhraní.
                    
                    barrier_geom = None
                    barrier_source = None
                    
                    if rozhrani_body and arcpy.Exists(rozhrani_body):
                        barrier_source = rozhrani_body
                    elif vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
                         # Fallback na linie, kdyby body nebyly (nemělo by nastat)
                        barrier_source = vr_rozhrani_layer
                    
                    if barrier_source:
                        try:
                            # Tolerance 2cm (trochu víc než snap 1cm)
                            arcpy.analysis.Buffer(barrier_source, r"memory\rozhrani_buffer", "0.02 Meters")
                            # Načti buffer jako geometrii pro rychlý test
                            if int(arcpy.GetCount_management(r"memory\rozhrani_buffer")[0]) > 0:
                                barrier_geom = arcpy.CopyFeatures_management(r"memory\rozhrani_buffer", arcpy.Geometry())[0]
                        except Exception as e:
                            log_message(f"Nepodařilo se vytvořit bariéry pro propagaci: {e}", "WARN")
                            barrier_geom = None
                    else:
                        log_message("Žádná CAD rozhraní - propagace poběží bez bariér", "INFO")

                    # 2. Načti segmenty
                    # OID -> {geom, attrs, has_data, orig_fid, sc_type}
                    segments_data = {}
                    
                    # Zkontrolujeme pole
                    fields_in_sc = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                    
                    has_orig_fid_field = "ORIG_FID" in fields_in_sc
                    has_sc_type_field = "SC_TYPE" in fields_in_sc
                    
                    cursor_fields = ["OBJECTID", "SHAPE@"] + available_height_attrs
                    if has_orig_fid_field: cursor_fields.append("ORIG_FID")
                    if has_sc_type_field: cursor_fields.append("SC_TYPE")
                    
                    with arcpy.da.SearchCursor(r"memory\sc_final_sj", cursor_fields) as cursor:
                        for row in cursor:
                            oid = row[0]
                            geom = row[1]
                            attr_len = len(available_height_attrs)
                            attrs = list(row[2:2+attr_len])
                            
                            # Parsuj extra fieldy
                            current_idx = 2 + attr_len
                            
                            orig_fid = -1
                            if has_orig_fid_field:
                                orig_fid = row[current_idx]
                                current_idx += 1
                                
                            sc_type = None
                            if has_sc_type_field:
                                raw_type = row[current_idx]
                                if raw_type:
                                    sc_type = str(raw_type).strip().lower() # Normalizace pro porovnání
                                else:
                                    sc_type = None
                                current_idx += 1
                            
                            # Determine has_data, strictly excluding ORIG_FID or generic fields
                            # attrs list corresponds to available_height_attrs
                            has_real_data = False
                            for idx, attr_val in enumerate(attrs):
                                field_name = available_height_attrs[idx]
                                # Ignorujeme technická pole pro určení, zda má segment "data" k propagaci
                                if "ORIG_FID" in field_name or "SC_TYPE" in field_name or "TARGET_FID" in field_name:
                                    continue
                                if attr_val is not None:
                                    has_real_data = True
                                    break
                            
                            segments_data[oid] = {
                                "geom": geom, 
                                "attrs": attrs, 
                                "has_data": has_real_data, 
                                "orig_fid": orig_fid,
                                "sc_type": sc_type
                            }

                    # 3. Iterativní propagace
                    max_iterations = 10
                    
                    for i in range(max_iterations):
                        changes = 0
                        updates = {} # oid -> new_attrs
                        
                        # Projdi jen ty bez dat
                        null_segments = {k: v for k, v in segments_data.items() if not v["has_data"]}
                        filled_segments = {k: v for k, v in segments_data.items() if v["has_data"]}
                        
                        if not null_segments:
                            break
                            
                        log_message(f"Iterace {i+1}: Segmentů bez dat: {len(null_segments)}, s daty: {len(filled_segments)}", "DEBUG")

                        # Pro každý prázdný segment
                        for null_oid, null_info in null_segments.items():
                            null_geom = null_info["geom"]
                            null_fid = null_info["orig_fid"]
                            null_type = null_info["sc_type"]
                            
                            # Najdi souseda s daty
                            candidate_attrs = None
                            
                            for fill_oid, fill_info in filled_segments.items():
                                fill_geom = fill_info["geom"]
                                fill_fid = fill_info["orig_fid"]
                                fill_type = fill_info["sc_type"]
                                
                                # Rychlý check disjoint (bounding box) - jen pro orientaci, distanceTo řeší vše
                                if null_geom.disjoint(fill_geom):
                                    pass 

                                # Check distance (tolerance 5cm pro napojení)
                                dist = null_geom.distanceTo(fill_geom)
                                
                                if dist < 0.05: 
                                    # Jsou propojené (nebo skoro)
                                    # log_message(f"  > OID {null_oid} (Type '{null_type}', FID {null_fid}) blízko OID {fill_oid} (Type '{fill_type}', FID {fill_fid}) (dist={dist:.4f}m)", "DEBUG")
                                    
                                    # Kde se dotýkají? 
                                    connection_point = None
                                    start_pt = null_geom.firstPoint
                                    if fill_geom.distanceTo(start_pt) < 0.05:
                                        connection_point = start_pt
                                    else:
                                        end_pt = null_geom.lastPoint
                                        if fill_geom.distanceTo(end_pt) < 0.05:
                                            connection_point = end_pt
                                    
                                    if not connection_point:
                                        connection_point = null_geom.firstPoint
                                    
                                    # Je tento bod chráněn bariérou?
                                    is_blocked = False
                                    if barrier_geom and connection_point:
                                        if not barrier_geom.disjoint(connection_point):
                                            # Bariéra nalezena.
                                            
                                            # LOGIKA ODBLOKOVÁNÍ:
                                            # 1. Pokud jsou to RŮZNÉ TYPY čar (např. roh bloku), bariéru ignorujeme.
                                            type_match = False
                                            if null_type is not None and fill_type is not None:
                                                 if null_type == fill_type:
                                                     type_match = True
                                            elif null_type is None and fill_type is None:
                                                type_match = True # Oba None považujeme za stejné (nedefinované)
                                            
                                            if not type_match:
                                                is_blocked = False
                                                # log_message(f"    - Bariéra ignorována (Různé SC_TYPE: '{null_type}' vs '{fill_type}')", "DEBUG")
                                            
                                            # 2. Fallback na ORIG_FID 
                                            elif null_fid != -1 and fill_fid != -1 and null_fid != fill_fid:
                                                is_blocked = False
                                                # log_message(f"    - Bariéra ignorována (Různé ORIG_FID: {null_fid} vs {fill_fid})", "DEBUG")
                                            
                                            else:
                                                is_blocked = True
                                                # log_message(f"    - Spojení blokováno bariérou (Stejný typ '{null_type}' i FID {null_fid})", "DEBUG")
                                    
                                    if not is_blocked:
                                        # log_message(f"    - Spojení OK -> Přebírám atributy", "DEBUG")
                                        candidate_attrs = fill_info["attrs"]
                                        break # Našli jsme dárce
                            
                            if candidate_attrs:
                                updates[null_oid] = candidate_attrs
                                changes += 1
                        
                        # Aplikuj změny do paměti a DB
                        if updates:
                            log_message(f"Iterace {i+1}: Propagováno {len(updates)} segmentů", "DEBUG")
                            
                            # Update DB
                            with arcpy.da.UpdateCursor(r"memory\sc_final_sj", ["OBJECTID"] + available_height_attrs) as cursor:
                                for row in cursor:
                                    oid = row[0]
                                    if oid in updates:
                                        new_attrs = updates[oid]
                                        for k, val in enumerate(new_attrs):
                                            row[k+1] = val
                                        cursor.updateRow(row)
                                        
                            # Update local cache
                            for oid, new_attrs in updates.items():
                                segments_data[oid]["attrs"] = new_attrs
                                segments_data[oid]["has_data"] = True
                        else:
                            log_message(f"Propagace dokončena po {i} iteracích", "OK")
                            break
                            
                    # Cleanup barriers
                    if arcpy.Exists(r"memory\rozhrani_buffer"):
                        arcpy.Delete_management(r"memory\rozhrani_buffer")

                
                # Dissolve podle TARGET_FID + SC_TYPE + VŠECHNY VÝŠKOVÉ ATRIBUTY


                
                # Dissolve podle TARGET_FID + SC_TYPE + VŠECHNY VÝŠKOVÉ ATRIBUTY
                log_message("Dissolve pro detekci chyb...", "STEP")
                
                # Dynamicky získej VR atributy z bloků
                if vr_circles and arcpy.Exists(vr_circles):
                    vr_attributes = get_vr_attributes(vr_circles)
                    log_message(f"VR atributy z bloků pro dissolve: {', '.join(vr_attributes) if vr_attributes else 'žádné'}", "DEBUG")
                else:
                    vr_attributes = []
                
                # Zjisti dostupné výškové atributy v sc_final_sj
                fields = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                available_height_attrs = []
                for attr in vr_attributes:
                    if attr in fields:
                        available_height_attrs.append(attr)
                
                log_message(f"Dostupné výškové atributy v finální vrstvě: {', '.join(available_height_attrs)}", "DEBUG")
                
                # Statistiky pro VŠECHNY výškové atributy
                # Dissolve pouze podle TARGET_FID + SC_TYPE → výšky jsou STATS (FIRST + UNIQUE)
                # Tím vzniknou UNIQUE_ pole pro detekci chyb (více VR bloků na jednom segmentu)
                stats_fields = []
                sj_field_names = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                for attr in available_height_attrs:
                    stats_fields.append(f"{attr} FIRST")
                    stats_fields.append(f"{attr} UNIQUE")
                if "ID_LOKAL" in sj_field_names:
                    stats_fields.append("ID_LOKAL FIRST")
                if "DRUH_SC" in sj_field_names:
                    stats_fields.append("DRUH_SC FIRST")
                if "DRUH_INFO" in sj_field_names:
                    stats_fields.append("DRUH_INFO FIRST")

                stats = ";".join(stats_fields) if stats_fields else ""

                # Dissolve pouze podle TARGET_FID + SC_TYPE (BEZ výškových atributů)
                dissolve_fields = ["TARGET_FID", "SC_TYPE"]

                log_message(f"Dissolve fields: {', '.join(dissolve_fields)}", "DEBUG")

                arcpy.management.Dissolve(
                    in_features=r"memory\sc_final_sj",
                    out_feature_class=r"memory\sc_final_dissolved",
                    dissolve_field=dissolve_fields,
                    statistics_fields=stats,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )

                # Přejmenuj FIRST_ATTR → ATTR pro přehlednost dalšího zpracování
                # (AlterField nepodporuje memory workspace → AddField + CalculateField + DeleteField)
                _type_map = {"String": "TEXT", "Double": "DOUBLE", "Single": "FLOAT",
                             "Short": "SHORT", "Long": "LONG", "Integer": "LONG", "Date": "DATE"}
                dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                _attrs_to_rename = list(dict.fromkeys(available_height_attrs + ["ID_LOKAL", "DRUH_SC", "DRUH_INFO"]))
                for attr in _attrs_to_rename:
                    first_name = f"FIRST_{attr}"
                    if first_name in dissolved_fields_dict and attr not in dissolved_fields_dict:
                        try:
                            first_field = dissolved_fields_dict[first_name]
                            fld_type = _type_map.get(first_field.type, "TEXT")
                            if first_field.type == "String":
                                arcpy.management.AddField(r"memory\sc_final_dissolved", attr, fld_type,
                                                          field_length=first_field.length)
                            else:
                                arcpy.management.AddField(r"memory\sc_final_dissolved", attr, fld_type)
                            arcpy.management.CalculateField(r"memory\sc_final_dissolved", attr,
                                                            f"!{first_name}!", "PYTHON3")
                            arcpy.management.DeleteField(r"memory\sc_final_dissolved", [first_name])
                            dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                        except Exception as e_ren:
                            log_message(f"Přejmenování {first_name} selhalo: {e_ren}", "WARN")

                # Rename known CAD field name aliases to canonical data model names
                # NUP_MAX (CAD typo) → NPU_MAX (data model), plus UNIQUE_NUP_MAX → UNIQUE_NPU_MAX
                dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                for cad_name, model_name in [("NUP_MAX", "NPU_MAX")]:
                    for _rsrc, _rdst in [(cad_name, model_name),
                                        (f"UNIQUE_{cad_name}", f"UNIQUE_{model_name}")]:
                        if _rsrc in dissolved_fields_dict and _rdst not in dissolved_fields_dict:
                            try:
                                _rf = dissolved_fields_dict[_rsrc]
                                _rftype = _type_map.get(_rf.type, "TEXT")
                                if _rf.type == "String":
                                    arcpy.management.AddField(r"memory\sc_final_dissolved", _rdst, _rftype,
                                                              field_length=_rf.length)
                                else:
                                    arcpy.management.AddField(r"memory\sc_final_dissolved", _rdst, _rftype)
                                arcpy.management.CalculateField(r"memory\sc_final_dissolved", _rdst,
                                                                f"!{_rsrc}!", "PYTHON3")
                                arcpy.management.DeleteField(r"memory\sc_final_dissolved", [_rsrc])
                                dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                            except Exception as e_cad:
                                log_message(f"Přejmenování CAD aliasu {_rsrc}→{_rdst} selhalo: {e_cad}", "WARN")

                sc_final_with_vr = r"memory\sc_final_dissolved"
                final_count = get_feature_count(sc_final_with_vr)
                log_message(f"Finální vrstva po dissolve: {final_count} segmentů", "OK")
                
                # DEBUG - kontrola SC_TYPE po finálním dissolve
                fields_final = [f.name for f in arcpy.ListFields(sc_final_with_vr)]
                if "SC_TYPE" in fields_final:
                    sc_types_found = set()
                    with arcpy.da.SearchCursor(sc_final_with_vr, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            if row[0]:
                                sc_types_found.add(row[0])
                    log_message(f"SC_TYPE po finálním dissolve: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
                else:
                    log_message("VAROVÁNÍ: SC_TYPE CHYBÍ po finálním dissolve!", "WARN")
                
                arcpy.Delete_management(r"memory\sc_final_sj")
                
            except Exception as e:
                log_message(f"Chyba při finálním připojení atributů: {e}", "ERROR")
                sc_final_with_vr = sc_cleaned
        else:
            # Pokud nejsou VR bloky, použij jen vyčištěné SC
            log_message("VR bloky nebyly nalezeny - pokračuji bez výškových atributů", "WARN")
            sc_final_with_vr = sc_cleaned
        
        # ============================================================
        # FÁZE 9: TVORBA VÝSTUPNÍCH VRSTEV DLE DATOVÉHO MODELU
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 9: TVORBA VÝSTUPNÍCH VRSTEV DLE DATOVÉHO MODELU", "STEP")
        log_message("=" * 60, "INFO")

        final_outputs = []
        errors_outputs = []

        if sc_final_with_vr:
            try:
                fields_in_final = [f.name for f in arcpy.ListFields(sc_final_with_vr)]

                # Zjisti, které výškové atributy jsou dostupné ve výsledné vrstvě
                available_height_attrs_final = [a for a in HEIGHT_ATTRIBUTES if a in fields_in_final]
                log_message(f"Dostupné výškové atributy ve finální vrstvě: {', '.join(available_height_attrs_final)}", "DEBUG")

                # --------------------------------------------------------
                # 9A: Z_3011_StavebniCara_l
                # Čistá geometrie SC (dissolve bez výškových atributů),
                # s DRUH_SC mapovaným z SC_TYPE a atributy datového modelu.
                # --------------------------------------------------------
                log_message("Tvořím Z_3011_StavebniCara_l...", "STEP")

                try:
                    # Dissolve všech SC segmentů podle SC_TYPE (zachová typ čáry, sloučí segmenty)
                    arcpy.management.Dissolve(
                        in_features=sc_final_with_vr,
                        out_feature_class=r"memory\sc_3011_dissolve",
                        dissolve_field=["SC_TYPE"],
                        statistics_fields=None,
                        multi_part="SINGLE_PART",
                        unsplit_lines="DISSOLVE_LINES"
                    )

                    sc_3011_name = f"{out_prefix}3011_StavebniCara_l" if out_prefix else "Z_3011_StavebniCara_l"
                    sc_3011_name = generate_unique_name(output_gdb, sc_3011_name)
                    sc_3011_fc = os.path.join(output_workspace, sc_3011_name)

                    arcpy.conversion.ExportFeatures(r"memory\sc_3011_dissolve", sc_3011_fc)
                    arcpy.Delete_management(r"memory\sc_3011_dissolve")

                    # Přidat atributy datového modelu
                    arcpy.management.AddField(sc_3011_fc, "SKNAZEV", "TEXT", field_length=50)
                    arcpy.management.AddField(sc_3011_fc, "OBTYPNAZEV", "TEXT", field_length=50)
                    arcpy.management.AddField(sc_3011_fc, "DRUH_SC", "TEXT", field_length=10)
                    arcpy.management.AddField(sc_3011_fc, "DRUH_INFO", "TEXT", field_length=255)
                    arcpy.management.AddField(sc_3011_fc, "ID_LOKAL", "SHORT")

                    # Naplnit atributy
                    with arcpy.da.UpdateCursor(sc_3011_fc, ["SC_TYPE", "SKNAZEV", "OBTYPNAZEV", "DRUH_SC"]) as cursor:
                        for row in cursor:
                            row[1] = "regulace struktury"
                            row[2] = "stavební čára"
                            row[3] = get_druh_sc_from_sc_type(row[0])
                            cursor.updateRow(row)

                    # Přenést DRUH_INFO z původní vrstvy (pokud existuje)
                    if "DRUH_INFO" in fields_in_final:
                        sc_3011_fields = [f.name for f in arcpy.ListFields(sc_3011_fc)]
                        if "DRUH_INFO" in sc_3011_fields:
                            # DRUH_INFO je prázdné, přenést z merged_sc_all pokud dostupné
                            try:
                                druh_info_map = {}
                                with arcpy.da.SearchCursor(sc_final_with_vr, ["SC_TYPE", "DRUH_INFO"]) as sc:
                                    for r in sc:
                                        if r[0] and r[1]:
                                            druh_info_map[r[0]] = r[1]
                                with arcpy.da.UpdateCursor(sc_3011_fc, ["SC_TYPE", "DRUH_INFO"]) as uc:
                                    for r in uc:
                                        if r[0] in druh_info_map:
                                            r[1] = druh_info_map[r[0]]
                                            uc.updateRow(r)
                            except Exception as e_di:
                                log_message(f"Přenos DRUH_INFO selhal: {e_di}", "WARN")

                    # Smazat pomocné pole SC_TYPE z výstupní vrstvy
                    sc_3011_existing = [f.name for f in arcpy.ListFields(sc_3011_fc)]
                    fields_to_remove_3011 = [f for f in sc_3011_existing
                                              if f not in ("OBJECTID", "Shape", "Shape_Length",
                                                           "SKNAZEV", "OBTYPNAZEV", "DRUH_SC",
                                                           "DRUH_INFO", "ID_LOKAL")
                                              and not arcpy.ListFields(sc_3011_fc, f)[0].required
                                              and arcpy.ListFields(sc_3011_fc, f)[0].type not in ("OID", "Geometry")]
                    if fields_to_remove_3011:
                        arcpy.management.DeleteField(sc_3011_fc, fields_to_remove_3011)

                    sc_3011_count = get_feature_count(sc_3011_fc)
                    log_message(f"Z_3011_StavebniCara_l: {sc_3011_count} prvků → {sc_3011_name}", "OK")
                    final_outputs.append(sc_3011_fc)

                except Exception as e:
                    log_message(f"Chyba při tvorbě Z_3011_StavebniCara_l: {e}", "ERROR")

                # --------------------------------------------------------
                # 9B: Z_3022_VyskovaRegulaceNaLinii_l
                # Všechny SC segmenty (i bez výšky), s výškovými atributy
                # přiřazenými spatial joinem. Obsahuje i NULL segmenty.
                # Detekce chyb: segmenty s více než jedním VR blokem.
                # --------------------------------------------------------
                log_message("Tvořím Z_3022_VyskovaRegulaceNaLinii_l...", "STEP")

                try:
                    # Dissolve POUZE podle výškových atributů (BEZ SC_TYPE, BEZ TARGET_FID)
                    # → segmenty od rozhraní k rozhraní se stejnou výškou se sloučí,
                    #   nezáleží na tom, zda jsou z různých SC typů
                    dissolve_fields_3022 = available_height_attrs_final if available_height_attrs_final else []

                    # Statistiky: ID_LOKAL + UNIQUE_ pole pro detekci chyb
                    stats_3022 = []
                    if "ID_LOKAL" in fields_in_final:
                        stats_3022.append("ID_LOKAL FIRST")
                    for attr in available_height_attrs_final:
                        unique_fname = f"UNIQUE_{attr}"
                        if unique_fname in fields_in_final:
                            stats_3022.append(f"{unique_fname} MAX")

                    arcpy.management.Dissolve(
                        in_features=sc_final_with_vr,
                        out_feature_class=r"memory\sc_3022_dissolve",
                        dissolve_field=dissolve_fields_3022,
                        statistics_fields=";".join(stats_3022) if stats_3022 else "",
                        multi_part="SINGLE_PART",
                        unsplit_lines="DISSOLVE_LINES"
                    )

                    vr_3022_name = f"{out_prefix}3022_VyskovaRegulaceNaLinii_l" if out_prefix else "Z_3022_VyskovaRegulaceNaLinii_l"
                    vr_3022_name = generate_unique_name(output_gdb, vr_3022_name)
                    vr_3022_fc = os.path.join(output_workspace, vr_3022_name)

                    arcpy.conversion.ExportFeatures(r"memory\sc_3022_dissolve", vr_3022_fc)
                    arcpy.Delete_management(r"memory\sc_3022_dissolve")

                    # Přejmenuj FIRST_ pole zpět na čistá jména a přidej atributy datového modelu
                    vr_3022_fields = [f.name for f in arcpy.ListFields(vr_3022_fc)]

                    # Výškové atributy jsou dissolve fields → jsou přímo jako VYSKA_VB, RIMSA_MAX atd.
                    # Přejmenovat jen FIRST_ID_LOKAL → ID_LOKAL (ID_LOKAL bylo v stats)
                    for attr in ["ID_LOKAL"]:
                        first_name = f"FIRST_{attr}"
                        if first_name in vr_3022_fields and attr not in vr_3022_fields:
                            arcpy.management.AlterField(vr_3022_fc, first_name, attr, attr)

                    # Aktualizuj seznam polí po přejmenování
                    vr_3022_fields = [f.name for f in arcpy.ListFields(vr_3022_fc)]

                    # Přidat SKNAZEV a OBTYPNAZEV pokud chybí
                    if "SKNAZEV" not in vr_3022_fields:
                        arcpy.management.AddField(vr_3022_fc, "SKNAZEV", "TEXT", field_length=50)
                    if "OBTYPNAZEV" not in vr_3022_fields:
                        arcpy.management.AddField(vr_3022_fc, "OBTYPNAZEV", "TEXT", field_length=50)
                    if "ID_LOKAL" not in vr_3022_fields:
                        arcpy.management.AddField(vr_3022_fc, "ID_LOKAL", "SHORT")

                    with arcpy.da.UpdateCursor(vr_3022_fc, ["SKNAZEV", "OBTYPNAZEV"]) as cursor:
                        for row in cursor:
                            row[0] = "regulace struktury"
                            row[1] = "výšková regulace na linii"
                            cursor.updateRow(row)

                    # Smazat nadbytečná pole - zachovat jen pole datového modelu
                    # + MAX_UNIQUE_* pole (potřebná pro error detection níže, smažou se po detekci)
                    keep_3022 = {"SKNAZEV", "OBTYPNAZEV", "ID_LOKAL",
                                 "VYSKA_VB", "VYSKA_VB_I",
                                 "NP_MIN", "NP_MAX", "NPU_MAX",
                                 "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX"}
                    vr_3022_fields_now = [f.name for f in arcpy.ListFields(vr_3022_fc)]
                    del_3022 = []
                    for fn in vr_3022_fields_now:
                        if fn in keep_3022:
                            continue
                        # Zachovat MAX_UNIQUE_* pro error detection (smažou se po detekci chyb)
                        if fn.startswith("MAX_UNIQUE_"):
                            continue
                        fi = arcpy.ListFields(vr_3022_fc, fn)[0]
                        if fi.required or fi.type in ("OID", "Geometry"):
                            continue
                        if fn.lower() in ("shape_length", "shape_area"):
                            continue
                        del_3022.append(fn)
                    if del_3022:
                        arcpy.management.DeleteField(vr_3022_fc, del_3022)

                    vr_3022_count = get_feature_count(vr_3022_fc)
                    log_message(f"Z_3022_VyskovaRegulaceNaLinii_l: {vr_3022_count} prvků → {vr_3022_name}", "OK")
                    final_outputs.append(vr_3022_fc)

                    # --------------------------------------------------------
                    # 9C: Z_3022_VyskovaRegulaceNaLinii_l_Errors
                    # Segmenty s více než jedním přiřazeným VR blokem
                    # (detekováno přes UNIQUE_RIMSA_MAX nebo UNIQUE jiného atributu > 1)
                    # --------------------------------------------------------
                    try:
                        # Detekce chyb: MAX_UNIQUE_ATTR > 1 = na alespoň jednom sub-segmentu
                        # bylo více VR bloků s různými hodnotami
                        unique_fields_in_vr = [f.name for f in arcpy.ListFields(vr_3022_fc)
                                               if f.name.startswith("MAX_UNIQUE_")]
                        if unique_fields_in_vr:
                            error_where = " OR ".join([f"{uf} > 1" for uf in unique_fields_in_vr])
                            # MakeFeatureLayer required: GetCount + ExportFeatures respect selection
                            # only when operating on a named layer, not a bare feature class path.
                            _err_lyr = "_vr3022_err_check"
                            arcpy.management.MakeFeatureLayer(vr_3022_fc, _err_lyr)
                            try:
                                arcpy.management.SelectLayerByAttribute(
                                    in_layer_or_view=_err_lyr,
                                    selection_type="NEW_SELECTION",
                                    where_clause=error_where
                                )
                                err_count = int(arcpy.GetCount_management(_err_lyr)[0])

                                if err_count > 0:
                                    vr_err_name = f"{out_prefix}3022_VyskovaRegulaceNaLinii_l_Errors" if out_prefix else "Z_3022_VyskovaRegulaceNaLinii_l_Errors"
                                    vr_err_name = generate_unique_name(output_gdb, vr_err_name)
                                    vr_err_fc = os.path.join(output_workspace, vr_err_name)
                                    arcpy.conversion.ExportFeatures(_err_lyr, vr_err_fc)
                                    log_message(f"Z_3022_Errors: {err_count} chybných segmentů → {vr_err_name}", "WARN")
                                    errors_outputs.append(vr_err_fc)
                                else:
                                    log_message("Z_3022: Žádné chyby (všechny segmenty mají max. 1 VR blok)", "OK")
                            finally:
                                arcpy.management.Delete(_err_lyr)

                            # Smazat UNIQUE_ pole z výsledné vrstvy (jsou jen pro interní detekci chyb)
                            arcpy.management.DeleteField(vr_3022_fc, unique_fields_in_vr)

                    except Exception as e_err:
                        log_message(f"Chyba při tvorbě vrstvy chyb Z_3022: {e_err}", "WARN")

                except Exception as e:
                    log_message(f"Chyba při tvorbě Z_3022_VyskovaRegulaceNaLinii_l: {e}", "ERROR")

                # --------------------------------------------------------
                # 9D: Export VR_NA_BOD (pokud existuje)
                # --------------------------------------------------------
                if vr_na_bod_layer and arcpy.Exists(vr_na_bod_layer):
                    try:
                        out_name_bod = f"{out_prefix}3021_VyskovaRegulaceNaBod_b" if out_prefix else "Z_3021_VyskovaRegulaceNaBod_b"
                        out_name_bod = generate_unique_name(output_gdb, out_name_bod)
                        out_fc_bod = os.path.join(output_workspace, out_name_bod)
                        arcpy.conversion.ExportFeatures(vr_na_bod_layer, out_fc_bod)

                        # Přidat SKNAZEV, OBTYPNAZEV
                        arcpy.management.AddField(out_fc_bod, "SKNAZEV", "TEXT", field_length=50)
                        arcpy.management.AddField(out_fc_bod, "OBTYPNAZEV", "TEXT", field_length=50)
                        with arcpy.da.UpdateCursor(out_fc_bod, ["SKNAZEV", "OBTYPNAZEV"]) as cur:
                            for row in cur:
                                row[0] = "regulace struktury"
                                row[1] = "výšková regulace na bod"
                                cur.updateRow(row)

                        final_outputs.append(out_fc_bod)
                        log_message(f"Z_3021_VyskovaRegulaceNaBod_b: exportováno → {out_name_bod}", "OK")
                    except Exception as e:
                        log_message(f"Chyba při exportu VR na bod: {e}", "WARN")

            except Exception as e:
                log_message(f"Kritická chyba ve Fázi 9: {e}", "ERROR")

        # ============================================================
        # FÁZE 10: CLEANUP
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 10: CLEANUP DOČASNÝCH VRSTEV", "STEP")
        log_message("=" * 60, "INFO")
        
        # Export rozhraní pro kontrolu (před cleanup) - DISABLED FOR FINAL CLEANUP
        # if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
        #     try:
        #         if out_prefix:
        #             rozhrani_name = f"{out_prefix}Rozhrani_body_kontrola"
        #         else:
        #             rozhrani_name = "Z_Rozhrani_body_kontrola"
        #         
        #         rozhrani_name = generate_unique_name(output_gdb, rozhrani_name)
        #         rozhrani_output = os.path.join(output_workspace, rozhrani_name)
        #         
        #         arcpy.CopyFeatures_management(rozhrani_body_all, rozhrani_output)
        #         rozhrani_count = get_feature_count(rozhrani_output)
        #         log_message(f"Export bodů rozhraní: {rozhrani_name} ({rozhrani_count} bodů)", "DEBUG")
        #     except Exception as e:
        #         log_message(f"Nepodařilo se exportovat body rozhraní: {e}", "WARN")
        
        # Export CAD linie rozhraní pro kontrolu - DISABLED FOR FINAL CLEANUP
        # if vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
        #     try:
        #         if out_prefix:
        #             rozhrani_line_name = f"{out_prefix}Rozhrani_linie_CAD"
        #         else:
        #             rozhrani_line_name = "Z_Rozhrani_linie_CAD"
        #         
        #         rozhrani_line_name = generate_unique_name(output_gdb, rozhrani_line_name)
        #         rozhrani_line_output = os.path.join(output_workspace, rozhrani_line_name)
        #         
        #         arcpy.CopyFeatures_management(vr_rozhrani_layer, rozhrani_line_output)
        #         rozhrani_line_count = get_feature_count(rozhrani_line_output)
        #         log_message(f"Export CAD linií rozhraní: {rozhrani_line_name} ({rozhrani_line_count} linií)", "DEBUG")
        #     except Exception as e:
        #         log_message(f"Nepodařilo se exportovat CAD linie rozhraní: {e}", "WARN")
        
        # Seznam memory vrstev k smazání
        memory_layers = [
            r"memory\sc_all_merged",
            r"memory\rozhrani_body_cad",
            r"memory\rozhrani_all",
            r"memory\sc_split_cad",
            r"memory\sc_with_vr",
            r"memory\sc_with_vr_temp",
            r"memory\sc_dissolve_clean",
            r"memory\sc_final_split",
            r"memory\sc_cleaned",
            r"memory\vr_linii_singlepart",
            r"memory\rozhrani_body_multipart",
            r"memory\rozhrani_lines_snap",
            r"memory\sc_3011_dissolve",
            r"memory\sc_3022_dissolve",
        ]
        
        deleted = 0
        for mem_layer in memory_layers:
            if arcpy.Exists(mem_layer):
                try:
                    arcpy.Delete_management(mem_layer)
                    deleted += 1
                except:
                    pass
        
        log_message(f"Smazáno {deleted} dočasných vrstev z paměti", "OK")
        
        # Smazání pomocných vrstev z output workspace (importované vrstvy a dočasné mezivýsledky)
        deleted_gdb = 0
        try:
            # Smazání původní vrstvy rozhraní a VR bloků
            layers_to_delete = [vr_rozhrani_layer, vr_na_bod_layer, vr_na_linii_layer, vr_circles]
            
            for layer in layers_to_delete:
                if layer and arcpy.Exists(layer):
                    arcpy.Delete_management(layer)
                    deleted_gdb += 1
                    
            # Smazání původních SC vrstev (jsou nahrazeny finálními výstupy s SC_TYPE)
            for sc_layer in sc_layers:
                if arcpy.Exists(sc_layer):
                    arcpy.Delete_management(sc_layer)
                    deleted_gdb += 1
        except Exception as e:
            log_message(f"Chyba při mazání pomocných vrstev v GDB: {e}", "WARN")
            
        log_message(f"Smazáno {deleted_gdb} importovaných vrstev z GDB", "OK")

        # ============================================================
        # SHRNUTÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("HOTOVO!", "OK")
        log_message("=" * 60, "INFO")
        
        if final_outputs:
            log_message(f"Vytvořeno {len(final_outputs)} výstupních vrstev:", "OK")
            for output_path in final_outputs:
                log_message(f"  • {os.path.basename(output_path)}", "OK")
        
        if errors_outputs:
            log_message(f"Vrstvy s chybami ({len(errors_outputs)}):", "WARN")
            for error_path in errors_outputs:
                log_message(f"  • {os.path.basename(error_path)}", "WARN")
        
        log_message(f"Output GDB: {output_gdb}", "INFO")

