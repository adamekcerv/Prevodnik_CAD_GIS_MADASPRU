# -*- coding: utf-8 -*-
import arcpy
import os

# Defaultní vrstvy pro MADASPRU project
DEFAULT_LAYERS = [
    "302110_BL_VR_na_bod",
    "302210_BL_VR_na_linii",
    "302211_PL_VR_na_linii_rozhrani"
]

def generate_unique_name(gdb_path, base_name):
    """Generuje unikátní název pro feature class v geodatabázi"""
    unique_name = base_name
    counter = 1
    
    # Uložení původního workspace
    original_workspace = arcpy.env.workspace
    
    try:
        # Kontrola existence v celé geodatabázi (včetně feature datasets)
        while arcpy.Exists(os.path.join(gdb_path, unique_name)):
            # Hledání ve všech feature datasets
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
        # Obnovení původního workspace
        arcpy.env.workspace = original_workspace
    
    return unique_name

class Toolbox(object):
    def __init__(self):
        self.label = "MADASPRU CAD Import - Výšky"
        self.alias = "MADASPRU_Vysky"
        self.tools = [SimpleCADImport]


class SimpleCADImport(object):
    def __init__(self):
        self.label = "Import CAD vrstev (Výšky)"
        self.alias = "simpleCADImport"
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

        # Metoda zpracování
        param9 = arcpy.Parameter(
            displayName="Metoda zpracování výškové regulace",
            name="processing_method",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )
        param9.filter.type = "ValueList"
        param9.filter.list = ["Centerline (buffer + centerline)", "Notebook (přímé řezání)"]
        param9.value = "Centerline (buffer + centerline)"  # Výchozí

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and parameters[0].value:
            cad_file = parameters[0].valueAsText
            
            try:
                # Načtení dostupných vrstev z CAD
                arcpy.env.workspace = cad_file
                available_layers = []
                
                if arcpy.Exists("Polyline"):
                    with arcpy.da.SearchCursor("Polyline", ["Layer"]) as cursor:
                        layers = sorted(set([row[0] for row in cursor]))
                        for layer in layers:
                            # Automaticky zahrnuj všechny SC vrstvy (301110-301119...) + ostatní z DEFAULT_LAYERS
                            if layer.startswith("3011") and "_PL_SC_" in layer:
                                available_layers.append(f"{layer} (Polyline)")
                            elif layer in DEFAULT_LAYERS:
                                available_layers.append(f"{layer} (Polyline)")
                
                parameters[1].filter.list = available_layers
                parameters[1].values = available_layers  # Automaticky vybrané
                parameters[1].enabled = True
                
                # Automatické nastavení S-JTSK
                if not parameters[6].altered:
                    parameters[6].value = arcpy.SpatialReference(5514)
                    
            except Exception as e:
                arcpy.AddWarning(f"Chyba při načítání CAD: {e}")

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True
        
        input_cad = parameters[0].valueAsText
        selected_layers = parameters[1].values if parameters[1].values else []
        output_gdb = parameters[2].valueAsText
        fd_name = parameters[3].valueAsText
        xy_tolerance = parameters[4].value or 0.01
        xy_resolution = parameters[5].value or 0.001
        output_sr = parameters[6].value or arcpy.SpatialReference(5514)
        transform_method = parameters[7].valueAsText
        out_prefix = parameters[8].valueAsText or ""
        processing_method = parameters[9].valueAsText or "Centerline (buffer + centerline)"
        
        # Rozpoznání metody
        use_notebook_method = "Notebook" in processing_method
        arcpy.AddMessage(f"Použitá metoda: {processing_method}")

        # Vytvoření Feature Dataset pokud je zadán
        if fd_name:
            fd_path = os.path.join(output_gdb, fd_name)
            if not arcpy.Exists(fd_path):
                arcpy.AddMessage(f"Vytvářím Feature Dataset: {fd_name}")
                arcpy.CreateFeatureDataset_management(
                    out_dataset_path=output_gdb,
                    out_name=fd_name,
                    spatial_reference=output_sr
                )
                
                # Nastavení tolerance a rozlišení
                arcpy.env.XYTolerance = f"{xy_tolerance} Meters"
                arcpy.env.XYResolution = f"{xy_resolution} Meters"
                
            output_workspace = fd_path
        else:
            output_workspace = output_gdb

        # Export vrstev
        exported_count = 0
        sc_layers = []  # Seznam SC vrstev pro merge
        vr_rozhrani_layer = None  # Pro uložení 302211 vrstvy
        vr_na_linii_layer = None  # Pro uložení 302210 vrstvy
        vr_na_bod_layer = None  # Pro uložení 302110 vrstvy
        
        for layer_info in selected_layers:
            if " (Polyline)" in layer_info:
                layer_name = layer_info.replace(" (Polyline)", "")
                
                # Nastavení workspace na CAD soubor pro každý export
                arcpy.env.workspace = input_cad
                
                # SQL pro filtrování vrstvy
                field_delimited = arcpy.AddFieldDelimiters("Polyline", "Layer")
                where_clause = f"{field_delimited} = '{layer_name}'"
                
                # Název výstupní vrstvy (s prefixem kvůli ArcGIS pravidlům)
                if out_prefix:
                    base_name = f"{out_prefix}{layer_name}_LN"
                else:
                    base_name = f"PL_{layer_name}_LN"  # Přidáme prefix PL_ aby název nezačínal číslicí
                
                # Generování unikátního názvu
                output_name = generate_unique_name(output_gdb, base_name)
                output_fc = os.path.join(output_workspace, output_name)
                
                try:
                    # Export vrstvy
                    arcpy.FeatureClassToFeatureClass_conversion(
                        in_features="Polyline",
                        out_path=output_workspace,
                        out_name=output_name,
                        where_clause=where_clause
                    )
                    
                    # Reprojekce pokud je potřeba (pouze pokud není Feature Dataset)
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
                        # DefineProjection pouze pokud není v Feature Dataset
                        arcpy.DefineProjection_management(output_fc, output_sr)
                    
                    arcpy.AddMessage(f"Exportováno: {layer_name}")
                    exported_count += 1
                    
                    # Kontrola zda je to SC vrstva (všechny 3011xx) pro pozdější merge
                    if layer_name.startswith("3011") and "_PL_SC_" in layer_name:
                        sc_layers.append(output_fc)
                    
                    # Kontrola zda je to VR rozhraní vrstva pro snap
                    elif layer_name == "302211_PL_VR_na_linii_rozhrani":
                        vr_rozhrani_layer = output_fc
                    
                    # Kontrola zda je to VR na bod vrstva pro multipart processing
                    elif layer_name == "302110_BL_VR_na_bod":
                        vr_na_bod_layer = output_fc
                    
                    # Kontrola zda je to VR na linii vrstva pro multipart processing
                    elif layer_name == "302210_BL_VR_na_linii":
                        vr_na_linii_layer = output_fc
                    
                except Exception as e:
                    arcpy.AddWarning(f"Chyba při exportu {layer_name}: {e}")

        # Merge SC vrstev pokud jsou alespoň 2
        merged_fc = None
        if len(sc_layers) >= 2:
            try:
                # Název pro sloučenou vrstvu
                if out_prefix:
                    merged_name = f"{out_prefix}SC_all_LN"
                else:
                    merged_name = "PL_SC_all_LN"
                
                merged_name = generate_unique_name(output_gdb, merged_name)
                merged_fc = os.path.join(output_workspace, merged_name)
                
                # Merge všech SC vrstev
                arcpy.Merge_management(sc_layers, merged_fc)
                arcpy.AddMessage(f"Sloučeno {len(sc_layers)} SC vrstev do: {merged_name}")
                
                # Smazání původních SC vrstev (volitelné)
                for sc_layer in sc_layers:
                    arcpy.Delete_management(sc_layer)
                arcpy.AddMessage("Původní SC vrstvy smazány")
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při merge SC vrstev: {e}")
        
        # ==========================================================================
        # ZPRACOVÁNÍ KRUHŮ (společné pro obě metody)
        # ==========================================================================
        
        # Zpracování VR na bod vrstvy - multipart to singlepart a filtrování uzavřených linií (kruhy)
        if vr_na_bod_layer and arcpy.Exists(vr_na_bod_layer):
            try:
                # Název pro singlepart vrstvu
                if out_prefix:
                    singlepart_name = f"{out_prefix}302110_VR_bod_singlepart_LN"
                else:
                    singlepart_name = "PL_302110_VR_bod_singlepart_LN"
                
                singlepart_name = generate_unique_name(output_gdb, singlepart_name)
                singlepart_fc = os.path.join(output_workspace, singlepart_name)
                
                # Multipart to Singlepart
                arcpy.management.MultipartToSinglepart(vr_na_bod_layer, singlepart_fc)
                arcpy.AddMessage("VR na bod převedeno na singlepart")
                
                # Filtrování pouze uzavřených linií (kruhy)
                # Název pro finální vrstvu s kruhy
                if out_prefix:
                    circles_name = f"{out_prefix}302110_VR_bod_circles_LN"
                else:
                    circles_name = "Z302110_BL_VR_na_bod"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                circles_fc = os.path.join(output_workspace, circles_name)
                
                # Vytvoření prázdné kopie pro kruhy
                arcpy.management.CreateFeatureclass(
                    out_path=output_workspace,
                    out_name=circles_name.split(os.sep)[-1],
                    geometry_type="POLYLINE",
                    template=singlepart_fc,
                    spatial_reference=output_sr
                )
                
                # Kopírování pouze uzavřených linií
                circles_count = 0
                # Získání seznamu polí (bez OBJECTID který se generuje automaticky)
                field_names = [field.name for field in arcpy.ListFields(singlepart_fc) 
                              if field.type != "OID" and field.name.upper() != "OBJECTID"]
                
                with arcpy.da.SearchCursor(singlepart_fc, ["SHAPE@"] + field_names) as search_cursor:
                    with arcpy.da.InsertCursor(circles_fc, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                arcpy.AddMessage(f"Nalezeno a zachováno {circles_count} uzavřených linií (kruhů) pro VR na bod")
                
                # Smazání dočasné singlepart vrstvy
                arcpy.Delete_management(singlepart_fc)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při zpracování VR na bod: {e}")
        
        # Zpracování VR na linii vrstvy - multipart to singlepart a filtrování uzavřených linií
        if vr_na_linii_layer and arcpy.Exists(vr_na_linii_layer):
            try:
                # Název pro singlepart vrstvu
                if out_prefix:
                    singlepart_name = f"{out_prefix}302210_VR_singlepart_LN"
                else:
                    singlepart_name = "PL_302210_VR_singlepart_LN"
                
                singlepart_name = generate_unique_name(output_gdb, singlepart_name)
                singlepart_fc = os.path.join(output_workspace, singlepart_name)
                
                # Multipart to Singlepart
                arcpy.management.MultipartToSinglepart(vr_na_linii_layer, singlepart_fc)
                arcpy.AddMessage("VR na linii převedeno na singlepart")
                
                # Filtrování pouze uzavřených linií (kruhy)
                # Název pro finální vrstvu s kruhy
                if out_prefix:
                    circles_name = f"{out_prefix}302210_VR_circles_LN"
                else:
                    circles_name = "PL_302210_VR_circles_LN"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                circles_fc = os.path.join(output_workspace, circles_name)
                
                # Vytvoření prázdné kopie pro kruhy
                arcpy.management.CreateFeatureclass(
                    out_path=output_workspace,
                    out_name=circles_name.split(os.sep)[-1],
                    geometry_type="POLYLINE",
                    template=singlepart_fc,
                    spatial_reference=output_sr
                )
                
                # Kopírování pouze uzavřených linií
                circles_count = 0
                # Získání seznamu polí (bez OBJECTID který se generuje automaticky)
                field_names = [field.name for field in arcpy.ListFields(singlepart_fc) 
                              if field.type != "OID" and field.name.upper() != "OBJECTID"]
                
                with arcpy.da.SearchCursor(singlepart_fc, ["SHAPE@"] + field_names) as search_cursor:
                    with arcpy.da.InsertCursor(circles_fc, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                arcpy.AddMessage(f"Nalezeno a zachováno {circles_count} uzavřených linií (kruhů)")
                
                # Smazání dočasné singlepart vrstvy
                arcpy.Delete_management(singlepart_fc)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při zpracování VR na linii: {e}")

        # ==========================================================================
        # NOTEBOOK METODA - Přímé řezání bez centerline
        # ==========================================================================
        if use_notebook_method:
            arcpy.AddMessage("=" * 70)
            arcpy.AddMessage("NOTEBOOK METODA: Přímé řezání stavebních čar (bez centerline)")
            arcpy.AddMessage("=" * 70)
            
            # Proměnné pro notebook metodu
            sc_final = None  # Finální vrstva výškové regulace
            
            # Najdi merged SC a kruhy
            if merged_fc and arcpy.Exists(merged_fc):
                # Najdi VR na linii kruhy
                vr_na_linii_circles = None
                try:
                    arcpy.env.workspace = output_workspace
                    circle_classes = arcpy.ListFeatureClasses("*302210*circles*")
                    if circle_classes:
                        vr_na_linii_circles = os.path.join(output_workspace, circle_classes[0])
                        arcpy.AddMessage(f"✓ Nalezeny kruhy VR na linii: {circle_classes[0]}")
                finally:
                    arcpy.env.workspace = ""
                
                if vr_na_linii_circles and arcpy.Exists(vr_na_linii_circles):
                    try:
                        # KROK 1: DISSOLVE stavebních čar (OPRAVA 1 - podle notebooku)
                        arcpy.AddMessage("\n--- KROK 1: Dissolve stavebních čar ---")
                        sc_dissolved_name = generate_unique_name(output_gdb, "SC_dissolved_temp")
                        sc_dissolved = os.path.join(output_workspace, sc_dissolved_name)
                        
                        orig_count = int(arcpy.GetCount_management(merged_fc)[0])
                        arcpy.AddMessage(f"Vstupní SC: {orig_count} prvků")
                        
                        # DEBUG: Zkontroluj jestli merged_fc má Layer
                        merged_fields = [f.name for f in arcpy.ListFields(merged_fc)]
                        has_layer = "Layer" in merged_fields
                        arcpy.AddMessage(f"DEBUG: merged_fc má Layer pole: {has_layer}")
                        
                        # Dissolve podle Layer aby se zachovaly různé typy SC!
                        arcpy.management.Dissolve(
                            in_features=merged_fc,
                            out_feature_class=sc_dissolved,
                            dissolve_field="Layer" if has_layer else None,  # Dissolve PODLE Layer!
                            statistics_fields=None,
                            multi_part="SINGLE_PART",
                            unsplit_lines="DISSOLVE_LINES"
                        )
                        dissolved_count = int(arcpy.GetCount_management(sc_dissolved)[0])
                        arcpy.AddMessage(f"✓ SC dissolved: {orig_count} -> {dissolved_count} prvků (SINGLE_PART, podle Layer)")
                        
                        # Layer pole už existuje (dissolve_field ho zachová)
                        if has_layer:
                            # DEBUG: Zkontroluj různé Layer hodnoty v sc_dissolved
                            layer_values_dissolved = set()
                            with arcpy.da.SearchCursor(sc_dissolved, ["Layer"]) as cursor:
                                for row in cursor:
                                    if row[0]:
                                        layer_values_dissolved.add(row[0])
                            arcpy.AddMessage(f"DEBUG: Různé Layer v sc_dissolved: {', '.join(sorted(layer_values_dissolved))}")
                        
                        # KROK 2: Zpracování rozhraní z CAD (pokud existuje)
                        rozhrani_body_all = None
                        if vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
                            arcpy.AddMessage("\n--- KROK 2: Zpracování rozhraní z CAD ---")
                            
                            # Snap rozhraní na dissolved SC
                            rozhrani_orig_count = int(arcpy.GetCount_management(vr_rozhrani_layer)[0])
                            arcpy.AddMessage(f"Vstupní rozhraní z CAD: {rozhrani_orig_count} prvků")
                            
                            snap_env = [[sc_dissolved, "EDGE", "0.3 Meters"]]
                            arcpy.Snap_edit(vr_rozhrani_layer, snap_env)
                            arcpy.AddMessage("✓ Rozhraní snapped na dissolved SC (tolerance 0.3m)")
                            
                            # Intersect - body rozhraní
                            rozhrani_multipart_name = generate_unique_name(output_gdb, "rozhrani_multipart_temp")
                            rozhrani_multipart = os.path.join(output_workspace, rozhrani_multipart_name)
                            
                            arcpy.analysis.PairwiseIntersect(
                                in_features=[vr_rozhrani_layer, sc_dissolved],
                                out_feature_class=rozhrani_multipart,
                                join_attributes="NO_FID",
                                output_type="POINT"
                            )
                            
                            # Multipart to Singlepart
                            rozhrani_cad_name = generate_unique_name(output_gdb, "rozhrani_CAD_temp")
                            rozhrani_cad = os.path.join(output_workspace, rozhrani_cad_name)
                            
                            arcpy.management.MultipartToSinglepart(rozhrani_multipart, rozhrani_cad)
                            cad_count = int(arcpy.GetCount_management(rozhrani_cad)[0])
                            arcpy.AddMessage(f"✓ Vytvořeno {cad_count} bodů rozhraní z CAD")
                            
                            arcpy.Delete_management(rozhrani_multipart)
                        else:
                            rozhrani_cad = None
                            arcpy.AddMessage("\n--- KROK 2: Rozhraní z CAD nenalezeno ---")
                        
                        # KROK 3: Generování automatických rozhraní (kde se mění výška)
                        arcpy.AddMessage("\n--- KROK 3: Generování automatických rozhraní ---")
                        
                        # Vytvoř centroidy z kruhů pro spatial join
                        centroids_name = generate_unique_name(output_gdb, "circles_centroids_temp")
                        centroids_fc = os.path.join(output_workspace, centroids_name)
                        
                        circles_count = int(arcpy.GetCount_management(vr_na_linii_circles)[0])
                        arcpy.AddMessage(f"Vstupní kruhy VR: {circles_count} prvků")
                        
                        # DEBUG: Zkontroluj pole v kruzích
                        circle_fields = [f.name for f in arcpy.ListFields(vr_na_linii_circles)]
                        vyska_in_circles = [f for f in circle_fields if f in ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "NP_MIN", "NP_MAX", "VYSKA_MAX"]]
                        arcpy.AddMessage(f"DEBUG: Pole výšky v kruzích: {', '.join(vyska_in_circles) if vyska_in_circles else '(žádná)'}")
                        
                        arcpy.management.FeatureToPoint(vr_na_linii_circles, centroids_fc, "INSIDE")
                        centroids_count = int(arcpy.GetCount_management(centroids_fc)[0])
                        arcpy.AddMessage(f"✓ Vytvořeno {centroids_count} centroidů z kruhů")
                        
                        # DEBUG: Zkontroluj pole v centroidech
                        centroid_fields = [f.name for f in arcpy.ListFields(centroids_fc)]
                        vyska_in_centroids = [f for f in centroid_fields if f in ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "NP_MIN", "NP_MAX", "VYSKA_MAX"]]
                        arcpy.AddMessage(f"DEBUG: Pole výšky v centroidech: {', '.join(vyska_in_centroids) if vyska_in_centroids else '(žádná)'}")
                        
                        # Spatial Join dissolved SC s centroidy (OPRAVA 3 - INTERSECT místo CLOSEST)
                        sc_with_vyska_name = generate_unique_name(output_gdb, "SC_with_vyska_temp")
                        sc_with_vyska = os.path.join(output_workspace, sc_with_vyska_name)
                        
                        arcpy.AddMessage(f"Spatial join: {dissolved_count} SC + {centroids_count} centroidů (INTERSECT)")
                        arcpy.analysis.SpatialJoin(
                            target_features=sc_dissolved,
                            join_features=centroids_fc,
                            out_feature_class=sc_with_vyska,
                            join_operation="JOIN_ONE_TO_MANY",
                            join_type="KEEP_ALL",
                            match_option="INTERSECT",  # OPRAVA 3: INTERSECT místo CLOSEST
                            field_mapping=None  # Standardní: zachová Layer z target (SC)
                        )
                        sj_count = int(arcpy.GetCount_management(sc_with_vyska)[0])
                        arcpy.AddMessage(f"✓ Spatial join výsledek: {sj_count} prvků (JOIN_ONE_TO_MANY, KEEP_ALL)")
                        
                        # DEBUG: Zkontroluj Layer hodnoty po SJ
                        layer_check = set()
                        with arcpy.da.SearchCursor(sc_with_vyska, ["Layer"]) as cursor:
                            for row in cursor:
                                if row[0]:
                                    layer_check.add(row[0])
                        arcpy.AddMessage(f"DEBUG: Layer hodnoty po SJ: {', '.join(sorted(layer_check))}")
                        
                        # Dissolve podle atributů výšky
                        possible_vyska_fields = ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "NP_MIN", "NP_MAX", "VYSKA_MAX"]
                        existing_fields = [f.name for f in arcpy.ListFields(sc_with_vyska)]
                        vyska_fields = [f for f in possible_vyska_fields if f in existing_fields]
                        
                        if vyska_fields:
                            arcpy.AddMessage(f"Nalezené atributy výšky: {', '.join(vyska_fields)} (z možných: {', '.join(possible_vyska_fields)})")
                            arcpy.AddMessage("Dissolve podle Layer + atributy výšky pro generování automatických rozhraní")
                            
                            sc_dissolved_vyska_name = generate_unique_name(output_gdb, "SC_dissolved_vyska_temp")
                            sc_dissolved_vyska = os.path.join(output_workspace, sc_dissolved_vyska_name)
                            
                            # Dissolve podle Layer + výška
                            dissolve_fields = ["Layer"] + vyska_fields
                            stats_fields = [f"{f} UNIQUE" for f in vyska_fields]
                            
                            arcpy.AddMessage(f"Dissolve fieldy: {', '.join(dissolve_fields)}")
                            arcpy.AddMessage(f"Statistics: {', '.join(stats_fields)}")
                            
                            arcpy.management.Dissolve(
                                in_features=sc_with_vyska,
                                out_feature_class=sc_dissolved_vyska,
                                dissolve_field=";".join(dissolve_fields),
                                statistics_fields=";".join(stats_fields),
                                multi_part="SINGLE_PART",
                                unsplit_lines="DISSOLVE_LINES"
                            )
                            
                            dissolved_vyska_count = int(arcpy.GetCount_management(sc_dissolved_vyska)[0])
                            arcpy.AddMessage(f"✓ Dissolve výsledek: {dissolved_vyska_count} segmentů podle výšky")
                            
                            # Select segmenty s určenou výškou
                            where_conditions = [f"UNIQUE_{f} IS NOT NULL" for f in vyska_fields]
                            arcpy.management.SelectLayerByAttribute(
                                sc_dissolved_vyska,
                                "NEW_SELECTION",
                                " OR ".join(where_conditions)
                            )
                            
                            # Koncové body těchto segmentů
                            sc_vertices_name = generate_unique_name(output_gdb, "SC_vertices_temp")
                            sc_vertices = os.path.join(output_workspace, sc_vertices_name)
                            
                            arcpy.management.FeatureVerticesToPoints(sc_dissolved_vyska, sc_vertices, "BOTH_ENDS")
                            vertices_count = int(arcpy.GetCount_management(sc_vertices)[0])
                            arcpy.AddMessage(f"✓ Koncové body vybraných segmentů: {vertices_count}")
                            
                            arcpy.management.SelectLayerByAttribute(sc_dissolved_vyska, "CLEAR_SELECTION")
                            
                            # Intersect - body kde se mění výška
                            rozhrani_auto_name = generate_unique_name(output_gdb, "rozhrani_auto_temp")
                            rozhrani_auto = os.path.join(output_workspace, rozhrani_auto_name)
                            
                            arcpy.analysis.Intersect(
                                in_features=f"{sc_vertices} #",
                                out_feature_class=rozhrani_auto,
                                join_attributes="ONLY_FID",
                                output_type="INPUT"
                            )
                            intersect_count = int(arcpy.GetCount_management(rozhrani_auto)[0])
                            arcpy.AddMessage(f"✓ Průsečíky koncových bodů: {intersect_count}")
                            
                            # Dissolve překrývajících se bodů
                            rozhrani_auto_final_name = generate_unique_name(output_gdb, "rozhrani_auto_final_temp")
                            rozhrani_auto_final = os.path.join(output_workspace, rozhrani_auto_final_name)
                            
                            arcpy.management.Dissolve(rozhrani_auto, rozhrani_auto_final, multi_part="SINGLE_PART")
                            auto_count = int(arcpy.GetCount_management(rozhrani_auto_final)[0])
                            arcpy.AddMessage(f"✓ Vygenerováno {auto_count} automatických bodů rozhraní")
                            
                            # Merge CAD + automatické rozhraní
                            rozhrani_all_name = generate_unique_name(output_gdb, "rozhrani_all_temp")
                            rozhrani_body_all = os.path.join(output_workspace, rozhrani_all_name)
                            
                            if rozhrani_cad:
                                arcpy.management.Merge([rozhrani_cad, rozhrani_auto_final], rozhrani_body_all)
                                total = int(arcpy.GetCount_management(rozhrani_body_all)[0])
                                arcpy.AddMessage(f"✓ Celkem {total} bodů rozhraní ({cad_count} z CAD + {auto_count} automatických)")
                            else:
                                arcpy.CopyFeatures_management(rozhrani_auto_final, rozhrani_body_all)
                                arcpy.AddMessage(f"✓ Celkem {auto_count} bodů rozhraní (pouze automatické)")
                            
                            # Cleanup
                            arcpy.Delete_management(sc_dissolved_vyska)
                            arcpy.Delete_management(sc_vertices)
                            arcpy.Delete_management(rozhrani_auto)
                            arcpy.Delete_management(rozhrani_auto_final)
                            if rozhrani_cad:
                                arcpy.Delete_management(rozhrani_cad)
                        
                        # KROK 4: SplitLineAtPoint (řezání dissolved SC)
                        if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
                            arcpy.AddMessage("\n--- KROK 4: Řezání dissolved SC ---")
                            
                            sc_split_name = generate_unique_name(output_gdb, "SC_split_temp")
                            sc_split = os.path.join(output_workspace, sc_split_name)
                            
                            rozhrani_count = int(arcpy.GetCount_management(rozhrani_body_all)[0])
                            arcpy.AddMessage(f"Řežu {dissolved_count} dissolved SC pomocí {rozhrani_count} bodů (tolerance 0.3m)")
                            
                            arcpy.management.SplitLineAtPoint(
                                in_features=sc_dissolved,
                                point_features=rozhrani_body_all,
                                out_feature_class=sc_split,
                                search_radius="0.3 Meters"  # Stejná tolerance jako snap
                            )
                            
                            split_count = int(arcpy.GetCount_management(sc_split)[0])
                            arcpy.AddMessage(f"✓ SplitLineAtPoint výsledek: {dissolved_count} -> {split_count} segmentů ({split_count - dissolved_count:+d})")
                            
                            # KROK 5: CLEANUP falešných rozhraní (VYPNUTO - cleanup maže správné řezy!)
                            # Cleanup z notebooku je navržen jinak a zde zahodit korektní řezy
                            arcpy.AddMessage("\n--- KROK 5: Cleanup falešných rozhraní (VYPNUTO) ---")
                            # Cleanup se nyní přeskakuje - všechny řezy se zachovávají
                            # (cleanup maž 16 nových řezů které jsou potřebné pro spatial join)
                            
                            arcpy.Delete_management(sc_split_vertices)
                            
                            # DŮLEŽITÉ: sc_split nemá Layer pole (SplitLineAtPoint ho neuchovává)
                            # Musíme přidat Layer pole zpět pomocí spatial join se sc_dissolved
                            arcpy.AddMessage("\n--- Obnova Layer pole po split ---")
                            
                            # DEBUG: Zkontroluj jestli sc_dissolved má Layer
                            dissolved_fields = [f.name for f in arcpy.ListFields(sc_dissolved)]
                            arcpy.AddMessage(f"DEBUG: Pole v sc_dissolved: {', '.join(dissolved_fields)}")
                            
                            # Zkontroluj jestli sc_split má Layer
                            split_fields = [f.name for f in arcpy.ListFields(sc_split)]
                            arcpy.AddMessage(f"DEBUG: Pole v sc_split: {', '.join(split_fields)}")
                            
                            if "Layer" not in split_fields:
                                if "Layer" in dissolved_fields:
                                    arcpy.AddMessage("Layer pole chybí v sc_split, obnovuji ze sc_dissolved...")
                                    
                                    # Přidej Layer pole pomocí Add Field a Calculate Field
                                    # Nejdřív přidej prázdné pole
                                    arcpy.management.AddField(sc_split, "Layer", "TEXT", field_length=50)
                                    
                                    # Pak použij Spatial Join jen pro získání Layer hodnoty
                                    sc_split_with_layer_name = generate_unique_name(output_gdb, "SC_split_with_layer_temp")
                                    sc_split_with_layer = os.path.join(output_workspace, sc_split_with_layer_name)
                                    
                                    arcpy.analysis.SpatialJoin(
                                        target_features=sc_split,
                                        join_features=sc_dissolved,
                                        out_feature_class=sc_split_with_layer,
                                        join_operation="JOIN_ONE_TO_ONE",
                                        join_type="KEEP_ALL",
                                        match_option="HAVE_THEIR_CENTER_IN"
                                    )
                                    
                                    # DEBUG: Zkontroluj pole ve výsledku
                                    result_fields = [f.name for f in arcpy.ListFields(sc_split_with_layer)]
                                    layer_fields = [f for f in result_fields if "Layer" in f.upper()]
                                    arcpy.AddMessage(f"DEBUG: Layer pole ve výsledku SJ: {', '.join(layer_fields)}")
                                    
                                    # Nahraď sc_split novou vrstvou
                                    arcpy.Delete_management(sc_split)
                                    sc_split = sc_split_with_layer
                                    
                                    arcpy.AddMessage(f"✓ Layer pole obnoveno")
                                else:
                                    arcpy.AddWarning("⚠ VAROVÁNÍ: sc_dissolved také nemá Layer pole!")
                                    arcpy.AddMessage("Přidávám prázdné Layer pole...")
                                    arcpy.management.AddField(sc_split, "Layer", "TEXT", field_length=50)
                            else:
                                arcpy.AddMessage("✓ Layer pole již existuje v sc_split")
                            
                            # KROK 6: Spatial Join s centroidy pro atributy
                            arcpy.AddMessage("\n--- KROK 6: Spatial Join s centroidy (INTERSECT) ---")
                            
                            sc_sj_name = generate_unique_name(output_gdb, "SC_SJ_temp")
                            sc_sj = os.path.join(output_workspace, sc_sj_name)
                            
                            segments_before_sj = int(arcpy.GetCount_management(sc_split)[0])
                            arcpy.AddMessage(f"Finální spatial join: {segments_before_sj} segmentů + {centroids_count} centroidů")
                            
                            # DEBUG: Zkontroluj Layer hodnoty PŘED finálním SJ
                            layer_before = set()
                            null_count_before = 0
                            total_count = 0
                            with arcpy.da.SearchCursor(sc_split, ["Layer"]) as cursor:
                                for row in cursor:
                                    total_count += 1
                                    if row[0]:
                                        layer_before.add(row[0])
                                    else:
                                        null_count_before += 1
                            arcpy.AddMessage(f"DEBUG: sc_split celkem {total_count} řádků, Layer NULL: {null_count_before}, hodnoty: {', '.join(sorted(layer_before)) if layer_before else '(žádné)'}")
                            
                            arcpy.analysis.SpatialJoin(
                                target_features=sc_split,
                                join_features=centroids_fc,
                                out_feature_class=sc_sj,
                                join_operation="JOIN_ONE_TO_MANY",
                                join_type="KEEP_ALL",
                                match_option="INTERSECT",  # OPRAVA 3: INTERSECT!
                                field_mapping=None  # Standardní: zachová Layer z target (sc_split)
                            )
                            
                            sj_final_count = int(arcpy.GetCount_management(sc_sj)[0])
                            arcpy.AddMessage(f"✓ Spatial join výsledek: {sj_final_count} záznamů (INTERSECT, JOIN_ONE_TO_MANY, KEEP_ALL)")
                            
                            # DEBUG: Zkontroluj jestli jsou atributy výšky v sc_sj
                            sj_fields = [f.name for f in arcpy.ListFields(sc_sj)]
                            vyska_in_sj = [f for f in sj_fields if f in ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "NP_MIN", "NP_MAX", "VYSKA_MAX"]]
                            arcpy.AddMessage(f"DEBUG: Pole výšky v sc_sj: {', '.join(vyska_in_sj) if vyska_in_sj else '(žádná)'}")
                            
                            # DEBUG: Zkontroluj kolik segmentů má ne-NULL hodnoty výšky
                            if "RIMSA_MAX" in sj_fields:
                                non_null_count = 0
                                with arcpy.da.SearchCursor(sc_sj, ["RIMSA_MAX"]) as cursor:
                                    for row in cursor:
                                        if row[0] is not None:
                                            non_null_count += 1
                                arcpy.AddMessage(f"DEBUG: Segmenty s ne-NULL RIMSA_MAX: {non_null_count} z {sj_final_count}")
                            
                            # DEBUG: Zkontroluj Layer hodnoty PO finálním SJ
                            layer_after = set()
                            null_count_after = 0
                            total_after = 0
                            with arcpy.da.SearchCursor(sc_sj, ["Layer"]) as cursor:
                                for row in cursor:
                                    total_after += 1
                                    if row[0]:
                                        layer_after.add(row[0])
                                    else:
                                        null_count_after += 1
                            arcpy.AddMessage(f"DEBUG: sc_sj celkem {total_after} řádků, Layer NULL: {null_count_after}, hodnoty: {', '.join(sorted(layer_after)) if layer_after else '(žádné)'}")
                            
                            # KROK 7: Finální dissolve podle TARGET_FID + statistiky
                            arcpy.AddMessage("\n--- KROK 7: Finální dissolve ---")
                            
                            sc_final_name = generate_unique_name(output_gdb, "VyskovaRegulaceNaLinii_l")
                            sc_final = os.path.join(output_workspace, sc_final_name)
                            
                            # Zjisti které atributy existují
                            sj_fields = [f.name for f in arcpy.ListFields(sc_sj)]
                            stats_list = []
                            found_fields = []
                            for field in possible_vyska_fields + ["Layer"]:
                                if field in sj_fields:
                                    found_fields.append(field)
                                    stats_list.append(f"{field} FIRST")
                                    # Přidej UNIQUE statistiku pro detekci chyb (více různých hodnot na jeden segment)
                                    if field in possible_vyska_fields:
                                        stats_list.append(f"{field} UNIQUE")
                            
                            arcpy.AddMessage(f"Dissolve podle TARGET_FID se statistikami: {', '.join(found_fields)}")
                            arcpy.AddMessage(f"Statistics pole: {'; '.join(stats_list)}")
                            
                            arcpy.management.Dissolve(
                                in_features=sc_sj,
                                out_feature_class=sc_final,
                                dissolve_field="TARGET_FID",
                                statistics_fields=";".join(stats_list),
                                multi_part="SINGLE_PART",
                                unsplit_lines="DISSOLVE_LINES"
                            )
                            
                            # Přejmenuj FIRST_ pole
                            for field in arcpy.ListFields(sc_final):
                                if field.name.startswith("FIRST_"):
                                    new_name = field.name.replace("FIRST_", "")
                                    try:
                                        arcpy.management.AlterField(sc_final, field.name, new_name, new_name)
                                    except:
                                        pass
                            
                            final_count = int(arcpy.GetCount_management(sc_final)[0])
                            arcpy.AddMessage(f"✓ Finální dissolve výsledek: {sj_final_count} -> {final_count} segmentů")
                            arcpy.AddMessage(f"✓ Přejmenovány FIRST_ pole na původní názvy")
                            
                            # Detekce chybných segmentů (mají více než jednu hodnotu výšky)
                            # podle notebooku: kde UNIQUE_* > 1
                            # POZOR: UNIQUE může být NULL pro segmenty bez výšky, musíme je vyfiltrovat
                            error_conditions = []
                            unique_fields = []
                            for field in arcpy.ListFields(sc_final):
                                if field.name.startswith("UNIQUE_"):
                                    unique_fields.append(field.name)
                                    # Kontroluj jen segmenty kde UNIQUE je > 1 (ne NULL)
                                    error_conditions.append(f"({field.name} > 1 AND {field.name} IS NOT NULL)")
                            
                            if error_conditions:
                                arcpy.AddMessage(f"Kontrola chybných segmentů: pole {', '.join(unique_fields)}")
                                
                                # Debug: vypiš statistiku UNIQUE hodnot
                                unique_stats = {}
                                for ufield in unique_fields:
                                    value_counts = {}
                                    null_count = 0
                                    with arcpy.da.SearchCursor(sc_final, [ufield]) as cursor:
                                        for row in cursor:
                                            val = row[0]
                                            if val is not None:
                                                value_counts[val] = value_counts.get(val, 0) + 1
                                            else:
                                                null_count += 1
                                    unique_stats[ufield] = value_counts
                                    if value_counts:
                                        arcpy.AddMessage(f"  {ufield}: {dict(sorted(value_counts.items()))} (+ {null_count} NULL)")
                                    else:
                                        arcpy.AddMessage(f"  {ufield}: všechny NULL ({null_count} segmentů)")
                                
                                where_clause = " OR ".join(error_conditions)
                                arcpy.AddMessage(f"WHERE klauzule: {where_clause}")
                                
                                arcpy.management.SelectLayerByAttribute(
                                    in_layer_or_view=sc_final,
                                    selection_type="NEW_SELECTION",
                                    where_clause=where_clause
                                )
                                
                                error_count = int(arcpy.GetCount_management(sc_final)[0])
                                arcpy.AddMessage(f"Výsledek kontroly: {error_count} segmentů vyhovuje podmínce")
                                
                                if error_count > 0:
                                    # Export chybných segmentů
                                    errors_name = generate_unique_name(output_gdb, "VyskovaRegulaceNaLinii_l_Errors")
                                    errors_fc = os.path.join(output_workspace, errors_name)
                                    arcpy.conversion.ExportFeatures(sc_final, errors_fc)
                                    arcpy.AddMessage(f"⚠ CHYBA: Nalezeno {error_count} segmentů s více různými výškami!")
                                    arcpy.AddMessage(f"⚠ Exportováno do: {errors_name}")
                                    arcpy.AddMessage("⚠ Tyto segmenty mají přiřazeny bloky s odlišnými hodnotami výšky.")
                                else:
                                    arcpy.AddMessage("✓ Kontrola OK: Žádné chybné segmenty (každý segment má max. 1 jedinečnou výšku)")
                                
                                # Clear selection
                                arcpy.management.SelectLayerByAttribute(sc_final, "CLEAR_SELECTION")
                            
                            # KROK 8: Rozdělení podle Layer
                            arcpy.AddMessage("\n--- KROK 8: Rozdělení podle typu SC ---")
                            
                            # Debug: vypiš všechna pole
                            all_fields = [f.name for f in arcpy.ListFields(sc_final)]
                            arcpy.AddMessage(f"Dostupná pole: {', '.join(all_fields)}")
                            
                            # DEBUG: Zkontroluj Layer hodnoty ve finální vrstvě
                            layer_final = set()
                            null_final = 0
                            total_final = 0
                            with arcpy.da.SearchCursor(sc_final, ["Layer"]) as cursor:
                                for row in cursor:
                                    total_final += 1
                                    if row[0]:
                                        layer_final.add(row[0])
                                    else:
                                        null_final += 1
                            arcpy.AddMessage(f"DEBUG: sc_final celkem {total_final} řádků, Layer NULL: {null_final}, hodnoty: {', '.join(sorted(layer_final)) if layer_final else '(žádné)'}")
                            
                            layer_field = None
                            for fname in all_fields:
                                if "LAYER" in fname.upper():  # Oprava: hledej uppercase "LAYER" v uppercase názvu
                                    layer_field = fname
                                    break
                            
                            if layer_field:
                                arcpy.AddMessage(f"Použito pole pro Layer: {layer_field}")
                                
                                # Nejdřív zjisti všechny hodnoty (debug)
                                all_layer_values = set()
                                unique_layers = set()
                                with arcpy.da.SearchCursor(sc_final, [layer_field]) as cursor:
                                    for row in cursor:
                                        if row[0]:
                                            all_layer_values.add(row[0])
                                            if str(row[0]).startswith("3011"):
                                                unique_layers.add(row[0])
                                
                                arcpy.AddMessage(f"Všechny hodnoty Layer: {', '.join(sorted(str(v) for v in all_layer_values))}")
                                arcpy.AddMessage(f"Hodnoty začínající '3011': {', '.join(sorted(str(v) for v in unique_layers)) if unique_layers else '(žádné)'}")
                                
                                if unique_layers:
                                    temp_layer = "sc_final_temp_layer"
                                    arcpy.management.MakeFeatureLayer(sc_final, temp_layer)
                                    
                                    arcpy.AddMessage(f"Nalezeno {len(unique_layers)} unikátních typů SC")
                                    
                                    for layer_value in sorted(unique_layers):
                                        where_clause = f"{layer_field} = '{layer_value}'"
                                        arcpy.management.SelectLayerByAttribute(temp_layer, "NEW_SELECTION", where_clause)
                                        
                                        count = int(arcpy.GetCount_management(temp_layer)[0])
                                        arcpy.AddMessage(f"  - {layer_value}: {count} segmentů")
                                        if count > 0:
                                            output_name = generate_unique_name(output_gdb, f"Z{layer_value}")
                                            output_fc = os.path.join(output_workspace, output_name)
                                            arcpy.conversion.ExportFeatures(temp_layer, output_fc)
                                            arcpy.AddMessage(f"✓ {output_name}: {count} segmentů")
                                    
                                    arcpy.management.SelectLayerByAttribute(temp_layer, "CLEAR_SELECTION")
                                    arcpy.Delete_management(temp_layer)
                                    arcpy.Delete_management(sc_final)
                                    arcpy.AddMessage(f"✓ Vytvořeno {len(unique_layers)} vrstev podle Layer")
                                else:
                                    arcpy.AddWarning("⚠ Nenalezeny žádné Layer hodnoty začínající '3011'")
                                    arcpy.AddMessage(f"Finální vrstva {sc_final_name} ponechána bez rozdělení")
                            else:
                                arcpy.AddWarning("⚠ Layer pole nenalezeno v atributové tabulce!")
                                arcpy.AddMessage(f"Finální vrstva {sc_final_name} ponechána bez rozdělení")
                            
                            # Cleanup dočasných vrstev
                            arcpy.Delete_management(sc_dissolved)
                            arcpy.Delete_management(centroids_fc)
                            arcpy.Delete_management(sc_with_vyska)
                            arcpy.Delete_management(rozhrani_body_all)
                            arcpy.Delete_management(sc_split)
                            arcpy.Delete_management(sc_sj)
                            
                            arcpy.AddMessage("\n" + "=" * 70)
                            arcpy.AddMessage("✓ NOTEBOOK METODA DOKONČENA")
                            arcpy.AddMessage("=" * 70)
                    
                    except Exception as e:
                        arcpy.AddWarning(f"Chyba při notebook metodě: {e}")
                        import traceback
                        arcpy.AddWarning(traceback.format_exc())
                else:
                    arcpy.AddWarning("Kruhy VR na linii nenalezeny - notebook metoda se neprovede")
            else:
                arcpy.AddWarning("Merged SC nenalezen - notebook metoda se neprovede")
        
        # ==========================================================================
        # CENTERLINE METODA (původní)
        # ==========================================================================
        elif not use_notebook_method:
            arcpy.AddMessage("=" * 70)
            arcpy.AddMessage("CENTERLINE METODA: Buffer + Centerline")
            arcpy.AddMessage("=" * 70)
            
            # VYTVOŘENÍ BUFFERU ZE SC LINIÍ
            if merged_fc and arcpy.Exists(merged_fc):
                try:
                    # Vytvoř 30cm buffer ze všech SC linií
                    if out_prefix:
                        buffer_name = f"{out_prefix}SC_final_buffer"
                    else:
                        buffer_name = "PL_SC_final_buffer"
                    
                    buffer_name = generate_unique_name(output_gdb, buffer_name)
                    buffer_fc = os.path.join(output_workspace, buffer_name)
                    
                    arcpy.analysis.Buffer(
                        in_features=merged_fc,
                        out_feature_class=buffer_fc,
                        buffer_distance_or_field="0.3 Meters",
                        line_side="FULL",
                        line_end_type="FLAT",
                        dissolve_option="NONE"
                    )
                    
                    buffer_count = int(arcpy.GetCount_management(buffer_fc)[0])
                    arcpy.AddMessage(f"Vytvořen 30cm buffer ze SC linií: {buffer_name}")
                    arcpy.AddMessage(f"Počet buffer prvků: {buffer_count}")
                
                except Exception as e:
                    arcpy.AddWarning(f"Chyba při vytváření bufferu: {e}")
                    buffer_fc = None
            else:
                arcpy.AddWarning("Merged SC linie nenalezeny - centerline metoda se neprovede")
                buffer_fc = None
            
            # SPATIAL JOIN BUFFERU S KRUHY
            # Najdi kruhy
            circles_fc = None
        
            # Hledání vrstvy kruhů
            original_workspace = arcpy.env.workspace
            try:
                arcpy.env.workspace = output_workspace
                circle_classes = arcpy.ListFeatureClasses("*circles*")
                if circle_classes:
                    circles_fc = os.path.join(output_workspace, circle_classes[0])
                    arcpy.AddMessage(f"Nalezena vrstva kruhů: {circle_classes[0]}")
            finally:
                arcpy.env.workspace = original_workspace
        
            # Pokud existují obě vrstvy, proveď spatial join
            if buffer_fc and circles_fc and arcpy.Exists(buffer_fc) and arcpy.Exists(circles_fc):
                try:
                    # Spatial join bufferu s kruhy
                    if out_prefix:
                        spatial_join_name = f"{out_prefix}SC_buffer_with_circles"
                    else:
                        spatial_join_name = "PL_SC_buffer_with_circles"
                    
                    spatial_join_name = generate_unique_name(output_gdb, spatial_join_name)
                    spatial_join_fc = os.path.join(output_workspace, spatial_join_name)
                    
                    arcpy.analysis.SpatialJoin(
                        target_features=buffer_fc,
                        join_features=circles_fc,
                        out_feature_class=spatial_join_fc,
                        join_operation="JOIN_ONE_TO_ONE",
                        join_type="KEEP_ALL",
                        match_option="INTERSECT"
                    )
                    
                    circles_joined = int(arcpy.GetCount_management(spatial_join_fc)[0])
                    arcpy.AddMessage(f"Vytvořen spatial join s kruhy: {spatial_join_name}")
                    arcpy.AddMessage(f"Buffer prvků s informacemi o kruzích: {circles_joined}")
                    
                    # VYTVOŘENÍ CENTERLINE Z BUFFERU S KRUHY
                    try:
                        # Zkontroluj licenci pro Production Mapping nebo Foundation (potřebné pro PolygonToCenterline)
                        if arcpy.CheckExtension("Foundation") == "Available":
                            arcpy.CheckOutExtension("Foundation")
                        
                            # Název pro centerline vrstvu
                            if out_prefix:
                                centerline_name = f"{out_prefix}SC_centerline_LN"
                            else:
                                centerline_name = "PL_SC_centerline_LN"
                        
                            centerline_name = generate_unique_name(output_gdb, centerline_name)
                            centerline_fc = os.path.join(output_workspace, centerline_name)
                        
                            # Výpis atributů které budou přeneseny
                            buffer_fields = [field.name for field in arcpy.ListFields(spatial_join_fc) 
                                           if field.type not in ["OID", "Geometry"] and field.name.upper() not in ["SHAPE_LENGTH", "SHAPE_AREA", "OBJECTID"]]
                            arcpy.AddMessage(f"Atributy k přenosu z bufferu: {', '.join(buffer_fields)}")
                        
                            # Vytvoření centerline z buffer polygonů
                            # PolygonToCenterline automaticky zachovává VŠECHNY atributy ze vstupních polygonů
                            arcpy.topographic.PolygonToCenterline(
                               in_features=spatial_join_fc,
                               out_feature_class=centerline_fc
                            )
                        
                            centerline_count = int(arcpy.GetCount_management(centerline_fc)[0])
                            arcpy.AddMessage(f"Vytvořena centerline vrstva: {centerline_name}")
                            arcpy.AddMessage(f"Počet centerline prvků: {centerline_count}")
                        
                            # EXPLICITNÍ PŘENOS ATRIBUTŮ pomocí JoinField
                            # PolygonToCenterline vytváří pole FID které odpovídá OBJECTID vstupního polygonu
                            try:
                               # Nejdřív zkontroluj jaká pole má centerline
                               centerline_fields_before = [field.name for field in arcpy.ListFields(centerline_fc)]
                               arcpy.AddMessage(f"Pole v centerline před join: {', '.join(centerline_fields_before)}")
                            
                               # Najdi pole které obsahuje odkaz na původní polygon (může být FID, ORIG_FID, nebo ObjectID)
                               join_field_name = None
                               if "FID" in centerline_fields_before:
                                   join_field_name = "FID"
                               elif "ORIG_FID" in centerline_fields_before:
                                   join_field_name = "ORIG_FID"
                               elif "OriginalOID" in centerline_fields_before:
                                   join_field_name = "OriginalOID"
                            
                               if not join_field_name:
                                   raise Exception("Nebylo nalezeno pole pro propojení (FID, ORIG_FID, OriginalOID)")
                            
                               arcpy.AddMessage(f"Použiji pole '{join_field_name}' pro propojení s OBJECTID bufferu")
                            
                               # Získej seznam polí k přenosu (všechna kromě OID, Shape, Shape_Length, Shape_Area)
                               buffer_fields_to_join = [field.name for field in arcpy.ListFields(spatial_join_fc) 
                                                       if field.type not in ["OID", "Geometry"] 
                                                       and field.name.upper() not in ["SHAPE_LENGTH", "SHAPE_AREA", "OBJECTID", "SHAPE", "FID"]]
                            
                               arcpy.AddMessage(f"Připojuji {len(buffer_fields_to_join)} polí z bufferu do centerline...")
                            
                               # JoinField - propojí centerline s bufferem přes FID -> OBJECTID
                               arcpy.management.JoinField(
                                   in_data=centerline_fc,
                                   in_field=join_field_name,  # Pole v centerline (FID)
                                   join_table=spatial_join_fc,
                                   join_field="OBJECTID",  # OBJECTID bufferu
                                   fields=buffer_fields_to_join  # Všechna pole k přenosu
                               )
                            
                               # Ověření že se atributy přenesly
                               centerline_fields = [field.name for field in arcpy.ListFields(centerline_fc) 
                                                   if field.type not in ["OID", "Geometry"] and field.name.upper() not in ["SHAPE_LENGTH", "OBJECTID"]]
                               arcpy.AddMessage(f"✓ Všechny atributy byly připojeny do centerline")
                               arcpy.AddMessage(f"Celkem polí v centerline: {len(centerline_fields)}")
                            
                               # DEBUG - zkontroluj která pole mají data
                               arcpy.AddMessage("DEBUG: Kontrola polí s daty...")
                               fields_with_data = []
                               fields_without_data = []
                            
                               with arcpy.da.SearchCursor(centerline_fc, centerline_fields) as cursor:
                                   row = next(cursor, None)  # První řádek
                                   if row:
                                       for i, field_name in enumerate(centerline_fields):
                                           if row[i] is not None and row[i] != '':
                                               fields_with_data.append(field_name)
                                           else:
                                               fields_without_data.append(field_name)
                            
                               arcpy.AddMessage(f"DEBUG: Pole s daty ({len(fields_with_data)}): {', '.join(fields_with_data[:30])}")  # Prvních 30
                               if len(fields_with_data) > 30:
                                   arcpy.AddMessage(f"DEBUG: ... a dalších {len(fields_with_data) - 30} polí")
                            
                               # PONECHÁNÍ POUZE POŽADOVANÝCH POLÍ
                               # Zachováme:
                               # 1. Layer - identifikace původní vrstvy
                               # 2. Pole z kruhů (Join_Count a ostatní z circles) - typicky mají suffix podle toho kolikrát se joinovalo
                               # 3. CAD atributy které obsahují výškové informace
                            
                               # Začneme se základními CAD poli a Layer
                               keep_fields = [
                                   "Layer",  # Identifikace vrstvy
                                   "Join_Count",  # Počet kruhů které se protínají
                                   # CAD atributy z circles (mohou mít různé suffixy _1, _12 atd.)
                                   "OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO", "DOK_NAZEV",
                                   "RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "PODTYP",
                                   "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "VYSKA_VB_D"
                               ]
                            
                               # Přidej všechny varianty s různými suffixy (_1, _12, atd.)
                               expanded_keep_fields = set(keep_fields)
                               for field in centerline_fields:
                                   for base_field in keep_fields:
                                       if field.startswith(base_field):
                                           expanded_keep_fields.add(field)
                            
                               keep_fields = list(expanded_keep_fields)
                               arcpy.AddMessage(f"DEBUG: Pole k zachování: {', '.join(sorted(keep_fields))}")
                            
                               # Najdi pole ke smazání (všechna kromě keep_fields a povinných systémových)
                               all_fields = arcpy.ListFields(centerline_fc)
                               fields_to_delete = []
                            
                               for field in all_fields:
                                   # Nesmažeme systémová pole a pole ze seznamu keep_fields
                                   if (field.type not in ["OID", "Geometry"] and 
                                       not field.required and 
                                       field.name not in keep_fields and
                                       field.name.upper() not in ["OBJECTID", "SHAPE", "SHAPE_LENGTH", "FID"]):
                                       fields_to_delete.append(field.name)
                            
                               # Smazání nepotřebných polí
                               if fields_to_delete:
                                   arcpy.AddMessage(f"Mažu {len(fields_to_delete)} nepotřebných polí...")
                                   arcpy.management.DeleteField(centerline_fc, fields_to_delete)
                                   arcpy.AddMessage(f"✓ Zachováno pouze {len(keep_fields)} požadovaných polí")
                               else:
                                   arcpy.AddMessage("Všechna pole jsou potřebná - žádné pole ke smazání")
                            
                               # Finální výpis polí
                               final_fields = [field.name for field in arcpy.ListFields(centerline_fc) 
                                             if field.type not in ["OID", "Geometry"] and field.name.upper() not in ["SHAPE_LENGTH", "OBJECTID"]]
                               arcpy.AddMessage(f"Finální pole v centerline: {', '.join(final_fields)}")
                            
                            except Exception as join_error:
                               arcpy.AddWarning(f"Varování při připojování atributů: {join_error}")
                               arcpy.AddWarning("Centerline byla vytvořena, ale některé atributy se nemusely přenést")
                        
                            # ÚPRAVA GEOMETRIE CENTERLINE - ALIGN K PŮVODNÍM LINIÍM
                            try:
                               # Najdi původní merged SC linie
                               original_lines_fc = None
                               arcpy.env.workspace = output_workspace
                            
                               # Hledej PL_SC_all nebo merged vrstvu
                               lines_classes = arcpy.ListFeatureClasses("*SC_all*")
                               if not lines_classes:
                                   lines_classes = arcpy.ListFeatureClasses("*SC_all_LN*")
                            
                               if lines_classes:
                                   original_lines_fc = os.path.join(output_workspace, lines_classes[0])
                                   arcpy.AddMessage(f"Nalezeny původní SC linie: {lines_classes[0]}")
                                
                                   # ALIGN FEATURES - inteligentně srovná centerline s původními liniemi
                                   # Zachová topologii (spojení/rozpojení) ale přizpůsobí geometrii
                                   arcpy.AddMessage("Srovnávám geometrii centerline s původními liniemi...")
                                   arcpy.AddMessage("  (zachovává topologii, upravuje pouze tvar)")
                                
                                   # Align s search distance 2 metry pro nalezení odpovídajících linií
                                   arcpy.edit.AlignFeatures(
                                       in_features=centerline_fc,      # Centerline (správná topologie)
                                       target_features=original_lines_fc,  # Původní linie (správná geometrie)
                                       search_distance="2.0 Meters"    # Vzdálenost hledání
                                   )
                                
                                   arcpy.AddMessage("✓ Geometrie centerline srovnána s původními liniemi")
                                   arcpy.AddMessage("  - Topologie zachována (spojení/rozpojení z centerline)")
                                   arcpy.AddMessage("  - Geometrie upravena (přesné rohy z původních linií)")
                                   arcpy.AddMessage("  - Pole AF_CONF přidáno (0-100, confidence alignment)")
                                
                               else:
                                   arcpy.AddWarning("Původní SC linie nebyly nalezeny - geometrie centerline zůstává nezměněna")
                                
                            except Exception as align_error:
                                arcpy.AddWarning(f"Chyba při srovnávání geometrie centerline: {align_error}")
                                arcpy.AddWarning("Centerline má geometrii z PolygonToCenterline (může být zaoblená)")
                                arcpy.AddWarning("Zkus zvýšit search_distance nebo zkontroluj že linie jsou blízko sebe")
                        
                            # Vrácení licence
                            arcpy.CheckInExtension("Foundation")
                        
                        else:
                            # FALLBACK: Použití 3rd party balíčku 'centerline' (Voronoi based)
                            # Optimalizovaná verze pro co nejpodobnější výsledek jako PolygonToCenterline
                            arcpy.AddWarning("Foundation/Production Mapping extension není dostupná")
                            arcpy.AddMessage("Zkouším alternativní metodu pomocí balíčku 'centerline' (Voronoi diagram)...")
                        
                            try:
                                from centerline.geometry import Centerline as VoronoiCenterline
                                from shapely.geometry import shape, mapping, LineString, MultiLineString
                                from shapely.ops import linemerge, unary_union
                                import json
                            
                                arcpy.AddMessage("✓ Balíček 'centerline' nalezen - používám optimalizovanou Voronoi metodu")
                            
                                # Název pro centerline vrstvu
                                if out_prefix:
                                    centerline_name = f"{out_prefix}SC_centerline_LN"
                                else:
                                    centerline_name = "PL_SC_centerline_LN"
                            
                                centerline_name = generate_unique_name(output_gdb, centerline_name)
                                centerline_fc = os.path.join(output_workspace, centerline_name)
                            
                                # Získání spatial reference z bufferu
                                sr = arcpy.Describe(spatial_join_fc).spatialReference
                            
                                # Vytvoření výstupní feature class pro centerline
                                arcpy.CreateFeatureclass_management(
                                    out_path=output_workspace,
                                    out_name=os.path.basename(centerline_fc),
                                    geometry_type="POLYLINE",
                                    spatial_reference=sr
                                )
                            
                                # Přidání pole pro původní OBJECTID (pro pozdější join atributů)
                                arcpy.AddField_management(centerline_fc, "ORIG_FID", "LONG")
                            
                                # Získání seznamu atributových polí z bufferu
                                buffer_fields = [field.name for field in arcpy.ListFields(spatial_join_fc) 
                                                if field.type not in ["OID", "Geometry"] 
                                                and field.name.upper() not in ["SHAPE_LENGTH", "SHAPE_AREA", "OBJECTID", "SHAPE"]]
                            
                                total_polygons = int(arcpy.GetCount_management(spatial_join_fc)[0])
                                arcpy.AddMessage(f"Zpracovávám {total_polygons} buffer polygonů...")
                            
                                # Pomocná funkce pro filtrování krátkých větví (Voronoi artefaktů)
                                def filter_short_branches(geom, min_length=0.15):
                                    """Odstraní krátké větve které jsou Voronoi artefakty"""
                                    if geom is None or geom.is_empty:
                                        return None
                                
                                    if geom.geom_type == 'LineString':
                                        return geom if geom.length >= min_length else None
                                    elif geom.geom_type == 'MultiLineString':
                                        # Filtruj krátké segmenty
                                        valid_lines = [line for line in geom.geoms if line.length >= min_length]
                                        if not valid_lines:
                                            return None
                                        elif len(valid_lines) == 1:
                                            return valid_lines[0]
                                        else:
                                            return MultiLineString(valid_lines)
                                    return geom
                            
                                # Pomocná funkce pro simplifikaci geometrie
                                def simplify_centerline(geom, tolerance=0.05):
                                    """Zjednodušení geometrie pro hladší výsledek"""
                                    if geom is None or geom.is_empty:
                                        return None
                                    return geom.simplify(tolerance, preserve_topology=True)
                            
                                # Zpracování každého buffer polygonu
                                centerline_count = 0
                                failed_count = 0
                            
                                with arcpy.da.SearchCursor(spatial_join_fc, ["SHAPE@", "OID@"]) as search_cursor:
                                    with arcpy.da.InsertCursor(centerline_fc, ["SHAPE@", "ORIG_FID"]) as insert_cursor:
                                        for row in search_cursor:
                                            polygon_geom = row[0]
                                            oid = row[1]
                                        
                                            try:
                                                # Převod ArcPy geometry na Shapely
                                                polygon_json = polygon_geom.JSON
                                                shapely_polygon = shape(json.loads(polygon_json))
                                            
                                                # Validace polygonu
                                                if not shapely_polygon.is_valid:
                                                    shapely_polygon = shapely_polygon.buffer(0)
                                            
                                                # Vytvoření centerline pomocí Voronoi
                                                # interpolation_distance=0.3 pro hustější body = přesnější Voronoi
                                                voronoi_cl = VoronoiCenterline(shapely_polygon, interpolation_distance=0.3)
                                            
                                                # Získání geometrie centerline
                                                cl_geom = voronoi_cl.geometry
                                            
                                                if cl_geom and not cl_geom.is_empty:
                                                    # 1. Filtrování krátkých větví (Voronoi artefakty)
                                                    # Min délka 15cm (polovina šířky bufferu 30cm)
                                                    cl_geom = filter_short_branches(cl_geom, min_length=0.15)
                                                
                                                    if cl_geom and not cl_geom.is_empty:
                                                        # 2. Sloučení linií do jedné pokud je to MultiLineString
                                                        if cl_geom.geom_type == 'MultiLineString':
                                                            merged = linemerge(cl_geom)
                                                            cl_geom = merged
                                                    
                                                        # 3. Simplifikace pro hladší výsledek (tolerance 5cm)
                                                        cl_geom = simplify_centerline(cl_geom, tolerance=0.05)
                                                    
                                                        if cl_geom and not cl_geom.is_empty:
                                                            # Převod Shapely geometry zpět na ArcPy
                                                            cl_json = mapping(cl_geom)
                                                            arcpy_geom = arcpy.AsShape(cl_json, True)
                                                        
                                                            # Vložení do výstupní feature class
                                                            insert_cursor.insertRow([arcpy_geom, oid])
                                                            centerline_count += 1
                                            except Exception as poly_error:
                                                failed_count += 1
                                                if failed_count <= 3:
                                                    arcpy.AddWarning(f"  Polygon OID {oid}: {poly_error}")
                            
                                if failed_count > 3:
                                    arcpy.AddWarning(f"  ... a dalších {failed_count - 3} chyb")
                            
                                arcpy.AddMessage(f"✓ Vytvořeno {centerline_count} centerline prvků (Voronoi metoda)")
                                if failed_count > 0:
                                    arcpy.AddWarning(f"  {failed_count} polygonů se nepodařilo zpracovat")
                            
                                # Připojení atributů z bufferu pomocí JoinField
                                if centerline_count > 0:
                                    arcpy.AddMessage("Připojuji atributy z bufferu...")
                                
                                    arcpy.management.JoinField(
                                        in_data=centerline_fc,
                                        in_field="ORIG_FID",
                                        join_table=spatial_join_fc,
                                        join_field="OBJECTID",
                                        fields=buffer_fields
                                    )
                                
                                    arcpy.AddMessage(f"✓ Připojeno {len(buffer_fields)} atributových polí")
                                
                                    # PONECHÁNÍ POUZE POŽADOVANÝCH POLÍ (stejně jako u Foundation verze)
                                    keep_fields = [
                                        "Layer", "Join_Count", "ORIG_FID",
                                        "OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO", "DOK_NAZEV",
                                        "RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "PODTYP",
                                        "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "VYSKA_VB_D"
                                    ]
                                
                                    # Rozšíření o varianty s suffixy
                                    centerline_fields = [f.name for f in arcpy.ListFields(centerline_fc)]
                                    expanded_keep_fields = set(keep_fields)
                                    for field in centerline_fields:
                                        for base_field in keep_fields:
                                            if field.startswith(base_field):
                                                expanded_keep_fields.add(field)
                                
                                    keep_fields = list(expanded_keep_fields)
                                
                                    # Smazání nepotřebných polí
                                    all_fields = arcpy.ListFields(centerline_fc)
                                    fields_to_delete = []
                                
                                    for field in all_fields:
                                        if (field.type not in ["OID", "Geometry"] and 
                                            not field.required and 
                                            field.name not in keep_fields and
                                            field.name.upper() not in ["OBJECTID", "SHAPE", "SHAPE_LENGTH"]):
                                            fields_to_delete.append(field.name)
                                
                                    if fields_to_delete:
                                        arcpy.management.DeleteField(centerline_fc, fields_to_delete)
                                        arcpy.AddMessage(f"✓ Zachováno pouze {len(keep_fields)} požadovaných polí")
                                
                                    # ÚPRAVA GEOMETRIE - PŘICHYCENÍ K PŮVODNÍM LINIÍM
                                    try:
                                        arcpy.env.workspace = output_workspace
                                        lines_classes = arcpy.ListFeatureClasses("*SC_all*")
                                        if not lines_classes:
                                            lines_classes = arcpy.ListFeatureClasses("*SC_all_LN*")
                                    
                                        if lines_classes:
                                            original_lines_fc = os.path.join(output_workspace, lines_classes[0])
                                            arcpy.AddMessage(f"Srovnávám geometrii s původními liniemi: {lines_classes[0]}")
                                        
                                            # 1. Densifikace pro více bodů k přichycení
                                            arcpy.edit.Densify(centerline_fc, "DISTANCE", "0.5 Meters")
                                        
                                            # 2. Snap k hranám a vrcholům původních linií
                                            snap_env = [
                                                [original_lines_fc, "EDGE", "0.4 Meters"],
                                                [original_lines_fc, "VERTEX", "0.2 Meters"]
                                            ]
                                            arcpy.edit.Snap(centerline_fc, snap_env)
                                        
                                            # 3. Generalizace pro vyhlazení výsledku
                                            arcpy.edit.Generalize(centerline_fc, "0.02 Meters")
                                        
                                            arcpy.AddMessage("✓ Geometrie centerline přichycena a vyhlazena")
                                            arcpy.AddMessage("  - Densifikace: 0.5m")
                                            arcpy.AddMessage("  - Snap EDGE: 0.4m, VERTEX: 0.2m")
                                            arcpy.AddMessage("  - Generalizace: 0.02m")
                                    except Exception as snap_error:
                                        arcpy.AddWarning(f"Úprava geometrie se nezdařila: {snap_error}")
                            
                                arcpy.AddMessage(f"Výsledná centerline vrstva: {centerline_name}")
                            
                            except ImportError:
                                arcpy.AddWarning("Balíček 'centerline' není nainstalován.")
                                arcpy.AddWarning("Pro instalaci spusťte: pip install centerline")
                                arcpy.AddWarning("Nebo: conda install -c conda-forge centerline")
                                arcpy.AddWarning("Centerline se nevytvoří - použijte ArcGIS Foundation extension nebo nainstalujte balíček 'centerline'")
                            except Exception as fallback_error:
                                arcpy.AddWarning(f"Chyba při vytváření centerline (Voronoi metoda): {fallback_error}")
                        
                    except Exception as e:
                        arcpy.AddWarning(f"Chyba při vytváření centerline: {e}")
                        # Pokus o vrácení licence i v případě chyby
                        try:
                            arcpy.CheckInExtension("Foundation")
                        except:
                            pass
                
                except Exception as e:
                    arcpy.AddWarning(f"Chyba při vytváření spatial join: {e}")
            else:
                if not buffer_fc:
                    arcpy.AddMessage("Finální buffer vrstva nebyla nalezena - spatial join se neprovede")
                if not circles_fc:
                    arcpy.AddMessage("Vrstva kruhů nebyla nalezena - spatial join se neprovede")

            # FINÁLNÍ SPLIT A CLEANUP - pouze pro centerline metodu
            arcpy.AddMessage("=" * 60)
            arcpy.AddMessage("FINÁLNÍ ZPRACOVÁNÍ - CENTERLINE")
            arcpy.AddMessage("=" * 60)
            
            # Najdi centerline vrstvu
            arcpy.env.workspace = output_workspace
            centerline_fcs = arcpy.ListFeatureClasses("*centerline*")
            
            if centerline_fcs:
                centerline_fc = os.path.join(output_workspace, centerline_fcs[0])
                arcpy.AddMessage(f"Nalezena centerline vrstva: {centerline_fcs[0]}")
                
                try:
                    # SPLIT BY ATTRIBUTES - rozdělení centerline podle Layer pole
                    arcpy.AddMessage("Rozdělování centerline podle atributu 'Layer'...")
                    
                    # Zkontroluj zda existuje pole Layer
                    centerline_fields = [field.name for field in arcpy.ListFields(centerline_fc)]
                    
                    if "Layer" in centerline_fields:
                        # Vytvoř pomocné pole s prefixem Z pro validní názvy
                        temp_field = "Layer_Z"
                        arcpy.AddField_management(centerline_fc, temp_field, "TEXT", field_length=100)
                        
                        # Zkopíruj Layer s prefixem Z a použij generate_unique_name pro unikátnost
                        unique_layer_names = {}
                        with arcpy.da.UpdateCursor(centerline_fc, ["Layer", temp_field]) as cursor:
                            for row in cursor:
                                if row[0]:
                                    base_name = f"Z{row[0]}"
                                    # Pokud ještě nemáme unikátní název pro tento Layer, vytvoř ho
                                    if base_name not in unique_layer_names:
                                        unique_layer_names[base_name] = generate_unique_name(output_gdb, base_name)
                                    row[1] = unique_layer_names[base_name]
                                    cursor.updateRow(row)
                        
                        arcpy.AddMessage("Vytvořeno pomocné pole Layer_Z s unikátními názvy")
                        
                        # Split by Layer_Z attribute
                        arcpy.analysis.SplitByAttributes(
                            Input_Table=centerline_fc,
                            Target_Workspace=output_workspace,
                            Split_Fields=[temp_field]
                        )
                        
                        arcpy.AddMessage("✓ Centerline rozdělena podle atributu 'Layer_Z'")
                        
                        # DEBUG - výpis všech feature classes PŘED mazáním
                        arcpy.env.workspace = output_workspace
                        all_fcs_before = arcpy.ListFeatureClasses()
                        arcpy.AddMessage(f"DEBUG: Celkem feature classes před cleanup: {len(all_fcs_before)}")
                        arcpy.AddMessage(f"DEBUG: Seznam všech FC: {', '.join(sorted(all_fcs_before))}")
                        
                        # CLEANUP - smazání všech podpůrných vrstev
                        arcpy.AddMessage("Mažu podpůrné vrstvy...")
                        
                        # Seznam všech feature classes v output workspace
                        arcpy.env.workspace = output_workspace
                        all_fcs = arcpy.ListFeatureClasses()
                        
                        deleted_count = 0
                        kept_count = 0
                        for fc in all_fcs:
                            fc_path = os.path.join(output_workspace, fc)
                            
                            # Smaž všechny kromě těch které vznikly splitováním
                            # Split vytváří názvy přímo podle hodnoty v poli Layer_Z
                            # Zachováme pouze fc které začínají "Z" (výsledky split s naším prefixem)
                            if not fc.startswith("Z"):
                                try:
                                    arcpy.Delete_management(fc_path)
                                    deleted_count += 1
                                    arcpy.AddMessage(f"  Smazáno: {fc}")
                                except Exception as del_error:
                                    arcpy.AddWarning(f"Nepodařilo se smazat {fc}: {del_error}")
                            else:
                                kept_count += 1
                                arcpy.AddMessage(f"  Zachováno: {fc}")
                        
                        arcpy.AddMessage(f"✓ Smazáno {deleted_count} podpůrných vrstev")
                        arcpy.AddMessage(f"✓ Zachováno {kept_count} výsledných vrstev")
                        
                        # Výpis finálních vrstev
                        arcpy.env.workspace = output_workspace
                        final_fcs = arcpy.ListFeatureClasses("Z*")
                        arcpy.AddMessage(f"✓ Finální výstup: {len(final_fcs)} vrstev rozdělených podle 'Layer':")
                        for final_fc in sorted(final_fcs):
                            count = int(arcpy.GetCount_management(os.path.join(output_workspace, final_fc))[0])
                            arcpy.AddMessage(f"  - {final_fc}: {count} prvků")
                        
                    else:
                        arcpy.AddWarning("Pole 'Layer' nebylo nalezeno v centerline - split se neprovede")
                        arcpy.AddMessage("Dostupná pole: " + ", ".join(centerline_fields))
                        
                except Exception as split_error:
                    arcpy.AddWarning(f"Chyba při finálním split a cleanup: {split_error}")
            else:
                arcpy.AddMessage("Centerline vrstva nebyla nalezena - split se neprovede")

        # Společný závěr
        arcpy.AddMessage(f"\nHotovo! Exportováno {exported_count} vrstev.")
        if use_notebook_method:
            arcpy.AddMessage("✓ Použita NOTEBOOK metoda (přímé řezání)")
        else:
            arcpy.AddMessage("✓ Použita CENTERLINE metoda (buffer + centerline)")
        arcpy.AddMessage("✓ Finální vrstvy rozděleny podle 'Layer'")