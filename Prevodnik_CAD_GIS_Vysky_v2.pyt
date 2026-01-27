# -*- coding: utf-8 -*-
"""
MADASPRU CAD Import - Výšky v2
Metoda: SplitLineAtPoint (bez buffer/centerline)
Logika převzata z HeightRegulationLine.ipynb
"""
import arcpy
import os

# Defaultní vrstvy pro MADASPRU project
DEFAULT_LAYERS = [
    "302110_BL_VR_na_bod",
    "302210_BL_VR_na_linii",
    "302211_PL_VR_na_linii_rozhrani"
]

# Výškové atributy pro dissolve a přenos
HEIGHT_ATTRIBUTES = [
    "RIMSA_MIN", "RIMSA_MAX",
    "NP_MIN", "NP_MAX", "NPU_MAX",
    "VYSKA_MAX", "VYSKA_VB", "VYSKA_VB_I"
]

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
        self.label = "Import CAD vrstev (Výšky) - SplitLine metoda"
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
                
                arcpy.analysis.PairwiseIntersect(
                    in_features=f"{vr_rozhrani_layer};{merged_sc_all}",
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
        # FÁZE 7: ČIŠTĚNÍ FALEŠNÝCH ROZHRANÍ (DOČASNĚ VYPNUTO)
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 7: ČIŠTĚNÍ FALEŠNÝCH ROZHRANÍ (PŘESKOČENO)", "STEP")
        log_message("=" * 60, "INFO")
        
        # DŮVOD VYPNUTÍ: Logika byla chybná - slučovala i segmenty s různými výškami
        # Řešení: Dissolve v FÁZI 8 podle výškových atributů to vyřeší lépe
        
        log_message("Čištění falešných rozhraní přeskočeno - použije se dissolve podle výšek", "INFO")
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
                log_message("Propagace atributů v oblastech mezi rozhraními...", "STEP")
                
                # Zjisti VR atributy
                if vr_circles and arcpy.Exists(vr_circles):
                    vr_attributes = get_vr_attributes(vr_circles)
                else:
                    vr_attributes = []
                
                fields = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                available_height_attrs = [attr for attr in vr_attributes if attr in fields]
                
                if available_height_attrs:
                    # Najdi segmenty s NULL vs s hodnotami
                    null_count = 0
                    filled_count = 0
                    
                    with arcpy.da.SearchCursor(r"memory\sc_final_sj", ["OBJECTID"] + available_height_attrs) as cursor:
                        for row in cursor:
                            has_value = any(row[i+1] is not None for i in range(len(available_height_attrs)))
                            if has_value:
                                filled_count += 1
                            else:
                                null_count += 1
                    
                    log_message(f"Segmentů s atributy: {filled_count}, bez atributů: {null_count}", "DEBUG")
                    
                    if null_count > 0 and filled_count > 0:
                        # Iterativní propagace přes sousedy (max 10 iterací)
                        log_message("Spouštím iterativní propagaci atributů...", "STEP")
                        
                        for iteration in range(10):
                            changes = 0
                            
                            # Načti všechny segmenty s jejich geometrií a atributy
                            segments = {}
                            with arcpy.da.SearchCursor(r"memory\sc_final_sj", 
                                                      ["OBJECTID", "SHAPE@"] + available_height_attrs) as cursor:
                                for row in cursor:
                                    oid = row[0]
                                    geom = row[1]
                                    attrs = list(row[2:])
                                    segments[oid] = {"geom": geom, "attrs": attrs}
                            
                            # Pro každý NULL segment najdi sousedy s hodnotami
                            updates = []
                            for oid, data in segments.items():
                                # Je NULL?
                                if all(attr is None for attr in data["attrs"]):
                                    # Najdi sousední segment s hodnotami
                                    for neighbor_oid, neighbor_data in segments.items():
                                        if neighbor_oid != oid:
                                            # Má soused hodnoty?
                                            if any(attr is not None for attr in neighbor_data["attrs"]):
                                                # Dotýkají se?
                                                if data["geom"].touches(neighbor_data["geom"]) or data["geom"].intersects(neighbor_data["geom"]):
                                                    # Zkopíruj atributy
                                                    updates.append((oid, neighbor_data["attrs"]))
                                                    changes += 1
                                                    break
                            
                            # Aplikuj změny
                            if updates:
                                with arcpy.da.UpdateCursor(r"memory\sc_final_sj", 
                                                          ["OBJECTID"] + available_height_attrs) as cursor:
                                    for row in cursor:
                                        oid = row[0]
                                        for update_oid, new_attrs in updates:
                                            if oid == update_oid:
                                                for i, attr in enumerate(new_attrs):
                                                    row[i+1] = attr
                                                cursor.updateRow(row)
                                                break
                                
                                log_message(f"Iterace {iteration+1}: propagováno {changes} segmentů", "DEBUG")
                            else:
                                log_message(f"Propagace dokončena po {iteration+1} iteracích", "OK")
                                break
                    else:
                        log_message("Propagace není potřeba (všechny segmenty mají nebo nemají atributy)", "DEBUG")
                
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
                stats_fields = []
                for attr in available_height_attrs:
                    stats_fields.append(f"{attr} FIRST")
                    stats_fields.append(f"{attr} COUNT")
                    stats_fields.append(f"{attr} UNIQUE")
                
                stats = ";".join(stats_fields) if stats_fields else ""
                
                # Dissolve podle TARGET_FID + SC_TYPE + VŠECHNY výškové atributy
                # Tím se NESLOUČÍ segmenty s různými výškami!
                dissolve_fields = ["TARGET_FID", "SC_TYPE"] + available_height_attrs
                
                log_message(f"Dissolve fields: {', '.join(dissolve_fields)}", "DEBUG")
                
                arcpy.management.Dissolve(
                    in_features=r"memory\sc_final_sj",
                    out_feature_class=r"memory\sc_final_dissolved",
                    dissolve_field=dissolve_fields,
                    statistics_fields=stats,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )
                
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
        # FÁZE 9: ROZDĚLENÍ PODLE TYPŮ SC + DETEKCE CHYB
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 9: ROZDĚLENÍ PODLE TYPŮ SC + DETEKCE CHYB", "STEP")
        log_message("=" * 60, "INFO")
        
        final_outputs = []
        errors_outputs = []
        
        if sc_final_with_vr:
            try:
                # DEBUG - detailní kontrola SC_TYPE před rozdělením
                fields = [f.name for f in arcpy.ListFields(sc_final_with_vr)]
                log_message(f"Dostupná pole před rozdělením: {', '.join(fields)}", "DEBUG")
                
                if "SC_TYPE" not in fields:
                    log_message("CHYBA: SC_TYPE pole NEEXISTUJE v finální vrstvě!", "ERROR")
                    log_message("Pravděpodobně bylo ztraceno během dissolve operace", "ERROR")
                    sc_types = [None]
                else:
                    # Zjisti dostupné typy SC s počtem
                    sc_types = set()
                    sc_type_counts = {}
                    null_count = 0
                    
                    with arcpy.da.SearchCursor(sc_final_with_vr, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            if row[0]:
                                sc_types.add(row[0])
                                sc_type_counts[row[0]] = sc_type_counts.get(row[0], 0) + 1
                            else:
                                null_count += 1
                    
                    if not sc_types:
                        log_message(f"SC_TYPE pole existuje, ale všechny hodnoty jsou NULL ({null_count} prvků)", "WARN")
                        log_message("Pravděpodobně bylo pole ztraceno během dissolve", "WARN")
                        sc_types = [None]
                    else:
                        log_message(f"Nalezeno {len(sc_types)} typů SC:", "OK")
                        for sc_type in sorted(sc_types):
                            log_message(f"  - {sc_type}: {sc_type_counts[sc_type]} segmentů", "DEBUG")
                        if null_count > 0:
                            log_message(f"  - NULL hodnot: {null_count} segmentů", "WARN")
                
                # Pro každý typ SC vytvoř samostatnou vrstvu
                for sc_type in sorted(sc_types):
                    if sc_type:
                        log_message("=" * 60, "INFO")
                        log_message(f"Zpracovávám typ: {sc_type}", "STEP")
                        
                        # Export s WHERE clause (místo selection - feature class nepodporuje selection)
                        if out_prefix:
                            output_name = f"{out_prefix}{sc_type}"
                        else:
                            output_name = f"Z_{sc_type}"
                        
                        output_name = generate_unique_name(output_gdb, output_name)
                        this_output = os.path.join(output_workspace, output_name)
                        
                        # WHERE clause s escapovaným názvem pole
                        field_delimited = arcpy.AddFieldDelimiters(sc_final_with_vr, "SC_TYPE")
                        where_clause = f"{field_delimited} = '{sc_type}'"
                        
                        log_message(f"WHERE: {where_clause}", "DEBUG")
                        
                        arcpy.conversion.ExportFeatures(
                            in_features=sc_final_with_vr,
                            out_features=this_output,
                            where_clause=where_clause
                        )
                        
                        final_count = get_feature_count(this_output)
                        log_message(f"Exportováno: {output_name} ({final_count} segmentů)", "OK")
                        
                        if final_count == 0:
                            log_message(f"VAROVÁNÍ: Žádné segmenty pro {sc_type}!", "WARN")
                            continue
                        
                        final_outputs.append((this_output, sc_type))
                        
                        # Detekce chyb (segmenty s více bloky S RŮZNÝMI hodnotami)
                        # Použij dynamické VR atributy místo hardcoded HEIGHT_ATTRIBUTES
                        if vr_circles and arcpy.Exists(vr_circles):
                            vr_attributes = get_vr_attributes(vr_circles)
                        else:
                            vr_attributes = []
                        
                        fields = [f.name for f in arcpy.ListFields(this_output)]
                        unique_field = None
                        for attr in vr_attributes:
                            if attr in fields:
                                unique_field = attr
                                break
                        
                        if unique_field:
                            count_field_name = f"COUNT_{unique_field}"
                            unique_field_name = f"UNIQUE_{unique_field}"
                            
                            if count_field_name in fields and unique_field_name in fields:
                                # Spočítej chyby ručně
                                manual_errors = 0
                                with arcpy.da.SearchCursor(this_output, [count_field_name, unique_field_name]) as cursor:
                                    for row in cursor:
                                        if row[0] is not None and row[0] > 0 and row[1] is not None and row[1] > 1:
                                            manual_errors += 1
                                
                                if manual_errors > 0:
                                    # WHERE clause pro chyby
                                    where_errors = f"{count_field_name} IS NOT NULL AND {count_field_name} > 0 AND {unique_field_name} > 1"
                                    
                                    if out_prefix:
                                        errors_name = f"{out_prefix}{sc_type}_Errors"
                                    else:
                                        errors_name = f"Z_{sc_type}_Errors"
                                    
                                    errors_name = generate_unique_name(output_gdb, errors_name)
                                    this_errors = os.path.join(output_workspace, errors_name)
                                    
                                    arcpy.conversion.ExportFeatures(
                                        in_features=this_output,
                                        out_features=this_errors,
                                        where_clause=where_errors
                                    )
                                    
                                    log_message(f"⚠️ {manual_errors} chyb → {errors_name}", "WARN")
                                    errors_outputs.append((this_errors, sc_type))
                                else:
                                    log_message("✅ Žádné chyby", "OK")
                    else:
                        # SC_TYPE bylo None - export jako jednu vrstvu
                        if out_prefix:
                            output_name = f"{out_prefix}VyskovaRegulaceNaLinii_l"
                        else:
                            output_name = "Z_VyskovaRegulaceNaLinii_l"
                        
                        output_name = generate_unique_name(output_gdb, output_name)
                        this_output = os.path.join(output_workspace, output_name)
                        
                        arcpy.CopyFeatures_management(sc_final_with_vr, this_output)
                        
                        final_count = get_feature_count(this_output)
                        log_message(f"Exportováno: {output_name} ({final_count} segmentů) - bez rozdělení typů", "OK")
                        final_outputs.append((this_output, "všechny_typy"))
                
            except Exception as e:
                log_message(f"Chyba při rozdělování podle typů SC: {e}", "ERROR")

        # ============================================================
        # FÁZE 10: CLEANUP
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 10: CLEANUP DOČASNÝCH VRSTEV", "STEP")
        log_message("=" * 60, "INFO")
        
        # Export rozhraní pro kontrolu (před cleanup)
        if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
            try:
                if out_prefix:
                    rozhrani_name = f"{out_prefix}Rozhrani_body_kontrola"
                else:
                    rozhrani_name = "Z_Rozhrani_body_kontrola"
                
                rozhrani_name = generate_unique_name(output_gdb, rozhrani_name)
                rozhrani_output = os.path.join(output_workspace, rozhrani_name)
                
                arcpy.CopyFeatures_management(rozhrani_body_all, rozhrani_output)
                rozhrani_count = get_feature_count(rozhrani_output)
                log_message(f"Export bodů rozhraní: {rozhrani_name} ({rozhrani_count} bodů)", "DEBUG")
            except Exception as e:
                log_message(f"Nepodařilo se exportovat body rozhraní: {e}", "WARN")
        
        # Export CAD linie rozhraní pro kontrolu
        if vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
            try:
                if out_prefix:
                    rozhrani_line_name = f"{out_prefix}Rozhrani_linie_CAD"
                else:
                    rozhrani_line_name = "Z_Rozhrani_linie_CAD"
                
                rozhrani_line_name = generate_unique_name(output_gdb, rozhrani_line_name)
                rozhrani_line_output = os.path.join(output_workspace, rozhrani_line_name)
                
                arcpy.CopyFeatures_management(vr_rozhrani_layer, rozhrani_line_output)
                rozhrani_line_count = get_feature_count(rozhrani_line_output)
                log_message(f"Export CAD linií rozhraní: {rozhrani_line_name} ({rozhrani_line_count} linií)", "DEBUG")
            except Exception as e:
                log_message(f"Nepodařilo se exportovat CAD linie rozhraní: {e}", "WARN")
        
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
            r"memory\sc_cleaned"
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
        
        # Smazání pomocných vrstev z output workspace
        try:
            if vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
                arcpy.Delete_management(vr_rozhrani_layer)
            # Smazání původních SC vrstev (jsou nahrazeny finálními výstupy s SC_TYPE)
            for sc_layer in sc_layers:
                if arcpy.Exists(sc_layer):
                    arcpy.Delete_management(sc_layer)
        except:
            pass

        # ============================================================
        # SHRNUTÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("HOTOVO!", "OK")
        log_message("=" * 60, "INFO")
        
        if final_outputs:
            log_message(f"Vytvořeno {len(final_outputs)} výstupních vrstev:", "OK")
            for output_path, type_name in final_outputs:
                log_message(f"  • {os.path.basename(output_path)}", "OK")
        
        if errors_outputs:
            log_message(f"Vrstvy s chybami ({len(errors_outputs)}):", "WARN")
            for error_path, type_name in errors_outputs:
                log_message(f"  • {os.path.basename(error_path)}", "WARN")
        
        log_message(f"Output GDB: {output_gdb}", "INFO")

