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
        
        # Nastavení výchozí hodnoty - aktuální projekt GDB nebo C:\GIS_Data\Output.gdb
        try:
            # Zkus použít Default.gdb z aktuálního projektu
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            param2.value = aprx.defaultGeodatabase
        except:
            # Fallback - pokud není projekt nebo selže
            default_path = r"C:\GIS_Data\Output.gdb"
            if arcpy.Exists(default_path):
                param2.value = default_path

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

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8]

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
                        
                        # DEBUG: Zkusme načíst atributy přímo z CAD Point (dynamic block insertion points)
                        arcpy.AddMessage(f"DEBUG - Zkouším načíst atributy z CAD Point pro {layer_name}...")
                        try:
                            arcpy.env.workspace = input_cad
                            if arcpy.Exists("Point"):
                                # Název pro point vrstvu
                                point_name = generate_unique_name(output_gdb, f"PL_{layer_name}_POINT")
                                point_fc = os.path.join(output_workspace, point_name)
                                
                                # Export Point s atributy
                                arcpy.FeatureClassToFeatureClass_conversion(
                                    in_features="Point",
                                    out_path=output_workspace,
                                    out_name=point_name,
                                    where_clause=f"{field_delimited} = '{layer_name}'"
                                )
                                
                                point_fields = [f.name for f in arcpy.ListFields(point_fc)]
                                arcpy.AddMessage(f"  Point pole ({len(point_fields)}): {', '.join(point_fields[:20])}")
                                
                                # Zkontroluj hodnoty
                                test_attrs = ["RIMSA_MIN", "VYSKA_VB", "NP_MIN", "VYSKA_MAX", "RefName"]
                                existing = [a for a in test_attrs if a in point_fields]
                                if existing:
                                    with arcpy.da.SearchCursor(point_fc, ["OID@"] + existing) as cursor:
                                        for i, row in enumerate(cursor):
                                            if i >= 3:
                                                break
                                            vals = ", ".join([f"{existing[j]}={row[j+1]}" for j in range(len(existing))])
                                            arcpy.AddMessage(f"    Point OID={row[0]}: {vals}")
                                
                                # Zjisti kolik bodů bylo exportováno
                                point_count = int(arcpy.GetCount_management(point_fc)[0])
                                arcpy.AddMessage(f"  Celkem Point prvků: {point_count}")
                            else:
                                arcpy.AddMessage("  Point feature class nenalezen v CAD")
                        except Exception as e:
                            arcpy.AddMessage(f"  Chyba při načítání Point: {e}")
                    
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
                
                # DEBUG: Zjisti jaké Layer hodnoty jsou v merged_fc
                layer_values = set()
                with arcpy.da.SearchCursor(merged_fc, ["Layer"]) as cursor:
                    for row in cursor:
                        if row[0]:
                            layer_values.add(row[0])
                arcpy.AddMessage(f"Layer hodnoty v merged SC: {layer_values}")
                
                # Smazání původních SC vrstev (volitelné)
                for sc_layer in sc_layers:
                    arcpy.Delete_management(sc_layer)
                arcpy.AddMessage("Původní SC vrstvy smazány")
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při merge SC vrstev: {e}")
        
        # NOVÝ PŘÍSTUP: Místo bufferu a centerline - přímé řezání stavebních čar pomocí rozhraní
        # Pokud není VR rozhraní, použijeme jen automaticky generovaná rozhraní
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("ZPRACOVÁNÍ VÝŠKOVÉ REGULACE - METODA BEZ CENTERLINE")
        arcpy.AddMessage("=" * 60)
        
        
        # KROK 1: Příprava stavebních čar pro řezání
        # DŮLEŽITÉ: NEPROVÁDÍME Dissolve před splitováním - pracujeme s původními liniemi!
        # Dissolve až POTOM pro cleanup falešných rozhraní
        merged_fc_original = merged_fc  # Původní SC linie s atributy
        
        if merged_fc and arcpy.Exists(merged_fc):
            arcpy.AddMessage("Krok 1: Původní stavební čáry připraveny")
            arcpy.AddMessage("  (Dissolve NEPROVÁDÍME - použije se až po splitování)")
            
        # KROK 2: Zpracování rozhraní z CAD (pokud existuje)
        rozhrani_body_cad = None
        if vr_rozhrani_layer and merged_fc and arcpy.Exists(vr_rozhrani_layer) and arcpy.Exists(merged_fc):
            arcpy.AddMessage("Krok 2: Zpracování rozhraní z CAD")
            try:
                # Snap tolerance 30 cm pro napojení (stejně jako starý kód)
                # SNAP NA PŮVODNÍ LINIE (merged_fc), NE na dissolved!
                snap_env = [[merged_fc, "EDGE", "0.3 Meters"]]
                arcpy.Snap_edit(vr_rozhrani_layer, snap_env)
                arcpy.AddMessage("✓ VR rozhraní napojeno na původní SC linie (tolerance 30 cm)")
                
                # Převedení rozhraní na body pomocí Pairwise Intersect
                # INTERSECT S PŮVODNÍMI LINIEMI (merged_fc), NE s dissolved!
                rozhrani_multipart_name = generate_unique_name(output_gdb, "rozhrani_body_multipart_temp")
                rozhrani_multipart_fc = os.path.join(output_workspace, rozhrani_multipart_name)
                
                arcpy.analysis.PairwiseIntersect(
                    in_features=[vr_rozhrani_layer, merged_fc],
                    out_feature_class=rozhrani_multipart_fc,
                    join_attributes="NO_FID",
                    cluster_tolerance=None,
                    output_type="POINT"
                )
                
                # Multipart to Singlepart
                rozhrani_body_name = generate_unique_name(output_gdb, "rozhrani_body_CAD_temp")
                rozhrani_body_cad = os.path.join(output_workspace, rozhrani_body_name)
                
                arcpy.management.MultipartToSinglepart(
                    in_features=rozhrani_multipart_fc,
                    out_feature_class=rozhrani_body_cad
                )
                
                cad_points_count = int(arcpy.GetCount_management(rozhrani_body_cad)[0])
                arcpy.AddMessage(f"✓ Vytvořeno {cad_points_count} bodů rozhraní z CAD")
                
                # Cleanup
                arcpy.Delete_management(rozhrani_multipart_fc)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při zpracování rozhraní z CAD: {e}")
        
        # Zpracování VR na bod vrstvy - multipart to singlepart a filtrování uzavřených linií (kruhy)
        circles_vr_na_bod = None
        if vr_na_bod_layer and arcpy.Exists(vr_na_bod_layer):
            try:
                arcpy.AddMessage("Krok 3: Zpracování VR na bod (kruhy)")
                # Název pro singlepart vrstvu
                if out_prefix:
                    singlepart_name = f"{out_prefix}302110_VR_bod_singlepart_LN"
                else:
                    singlepart_name = "PL_302110_VR_bod_singlepart_LN"
                
                singlepart_name = generate_unique_name(output_gdb, singlepart_name)
                singlepart_fc = os.path.join(output_workspace, singlepart_name)
                
                # Multipart to Singlepart
                arcpy.management.MultipartToSinglepart(vr_na_bod_layer, singlepart_fc)
                
                # Filtrování pouze uzavřených linií (kruhy)
                # Název pro finální vrstvu s kruhy
                if out_prefix:
                    circles_name = f"{out_prefix}302110_VR_bod_circles_LN"
                else:
                    circles_name = "PL_302110_BL_VR_na_bod"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                circles_vr_na_bod = os.path.join(output_workspace, circles_name)
                
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
                    with arcpy.da.InsertCursor(circles_vr_na_bod, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                arcpy.AddMessage(f"✓ Nalezeno {circles_count} uzavřených linií (kruhů) pro VR na bod")
                
                # Smazání dočasné singlepart vrstvy
                arcpy.Delete_management(singlepart_fc)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při zpracování VR na bod: {e}")
        
        # Zpracování VR na linii vrstvy - multipart to singlepart a filtrování uzavřených linií  
        circles_vr_na_linii = None
        if vr_na_linii_layer and arcpy.Exists(vr_na_linii_layer):
            try:
                arcpy.AddMessage("Krok 4: Zpracování VR na linii (kruhy)")
                
                # DEBUG: Zkontroluj jaká pole má původní CAD vrstva
                arcpy.AddMessage("DEBUG - Kontrola polí v původní CAD vrstvě 302210_BL_VR_na_linii...")
                orig_fields = [f.name for f in arcpy.ListFields(vr_na_linii_layer)]
                arcpy.AddMessage(f"  Celkem polí: {len(orig_fields)}")
                arcpy.AddMessage(f"  Všechna pole: {', '.join(orig_fields)}")
                
                # DEBUG: Zkontroluj hodnoty v prvních 3 prvcích PŘED singlepart
                arcpy.AddMessage("DEBUG - Hodnoty atributů v prvních 3 prvcích PŘED singlepart...")
                test_attrs = ["RIMSA_MIN", "VYSKA_VB", "NP_MIN", "VYSKA_MAX"]
                existing_attrs = [a for a in test_attrs if a in orig_fields]
                
                if existing_attrs:
                    with arcpy.da.SearchCursor(vr_na_linii_layer, ["OID@"] + existing_attrs) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 3:
                                break
                            attr_values = ", ".join([f"{attr}={row[j+1]}" for j, attr in enumerate(existing_attrs)])
                            arcpy.AddMessage(f"  Prvek OID={row[0]}: {attr_values}")
                else:
                    arcpy.AddWarning("  ⚠ Žádné z očekávaných atributů (RIMSA_MIN, VYSKA_VB, atd.) nebylo nalezeno!")
                    arcpy.AddMessage("  Hledej alternativní názvy v seznamu polí výše...")
                
                # Název pro singlepart vrstvu
                if out_prefix:
                    singlepart_name = f"{out_prefix}302210_VR_singlepart_LN"
                else:
                    singlepart_name = "PL_302210_VR_singlepart_LN"
                
                singlepart_name = generate_unique_name(output_gdb, singlepart_name)
                singlepart_fc = os.path.join(output_workspace, singlepart_name)
                
                # Multipart to Singlepart
                arcpy.management.MultipartToSinglepart(vr_na_linii_layer, singlepart_fc)
                
                # Filtrování pouze uzavřených linií (kruhy)
                # Název pro finální vrstvu s kruhy
                if out_prefix:
                    circles_name = f"{out_prefix}302210_VR_circles_LN"
                else:
                    circles_name = "PL_302210_VR_circles_LN"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                circles_vr_na_linii = os.path.join(output_workspace, circles_name)
                
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
                    with arcpy.da.InsertCursor(circles_vr_na_linii, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                arcpy.AddMessage(f"✓ Nalezeno {circles_count} uzavřených linií (kruhů)")
                
                # Smazání dočasné singlepart vrstvy
                arcpy.Delete_management(singlepart_fc)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při zpracování VR na linii: {e}")

        # KROK 5: Generování automatických rozhraní tam, kde se mění výška
        # (podle logiky z notebooku - Dissolve podle atributu výšky, hledání koncových bodů)
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("Krok 5: Generování automatických rozhraní")
        arcpy.AddMessage("=" * 60)
        
        rozhrani_body_all = None
        if circles_vr_na_linii and merged_fc and arcpy.Exists(circles_vr_na_linii) and arcpy.Exists(merged_fc):
            try:
                # Pro generování automatických rozhraní POTŘEBUJEME dissolved linie
                # (aby se našly místa kde se mění výška)
                arcpy.AddMessage("Dočasné rozpuštění SC pro hledání změn výšky...")
                
                dissolved_for_auto_name = generate_unique_name(output_gdb, "SC_dissolved_for_auto_temp")
                dissolved_for_auto_fc = os.path.join(output_workspace, dissolved_for_auto_name)
                
                arcpy.management.Dissolve(
                    in_features=merged_fc,
                    out_feature_class=dissolved_for_auto_fc,
                    dissolve_field="Layer",
                    statistics_fields=None,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )
                
                # Spatial join s dissolved liniemi pro hledání změn výšky
                arcpy.AddMessage("Spatial join dissolved SC s kruhy VR pro hledání změn výšky...")
                
                sc_with_vyska_name = generate_unique_name(output_gdb, "SC_with_vyska_temp")
                sc_with_vyska_fc = os.path.join(output_workspace, sc_with_vyska_name)
                
                # Získat všechna pole z kruhů (dynamické bloky)
                circle_fields = [field.name for field in arcpy.ListFields(circles_vr_na_linii) 
                                if field.type not in ["OID", "Geometry"] and field.name.upper() not in ["SHAPE_LENGTH", "OBJECTID"]]
                
                # Vytvoř field mapping pro spatial join - zachovej všechna pole
                field_mappings = arcpy.FieldMappings()
                field_mappings.addTable(dissolved_for_auto_fc)
                field_mappings.addTable(circles_vr_na_linii)
                
                arcpy.analysis.SpatialJoin(
                    target_features=dissolved_for_auto_fc,
                    join_features=circles_vr_na_linii,
                    out_feature_class=sc_with_vyska_fc,
                    join_operation="JOIN_ONE_TO_MANY",
                    join_type="KEEP_ALL",
                    field_mapping=field_mappings,
                    match_option="INTERSECT"
                )
                
                arcpy.AddMessage("✓ Atributy z kruhů připojeny k dissolved SC pro hledání změn")
                
                # Dissolve podle všech atributů výšky
                sc_dissolved_vyska_name = generate_unique_name(output_gdb, "SC_dissolved_vyska_temp")
                sc_dissolved_vyska_fc = os.path.join(output_workspace, sc_dissolved_vyska_name)
                
                # Možné atributy výšky z dynamických bloků
                possible_vyska_fields = ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "VYSKA_VB_D", 
                                        "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "ID_LOKAL"]
                
                # Zjisti které atributy skutečně existují v sc_with_vyska_fc
                existing_fields = [field.name for field in arcpy.ListFields(sc_with_vyska_fc)]
                vyska_fields = [field for field in possible_vyska_fields if field in existing_fields]
                
                if not vyska_fields:
                    raise Exception("Žádné atributy výšky nebyly nalezeny v datech")
                
                # Výpis použitých/chybějících atributů
                missing_fields = [field for field in possible_vyska_fields if field not in existing_fields]
                arcpy.AddMessage(f"Použité atributy výšky ({len(vyska_fields)}): {', '.join(vyska_fields)}")
                if missing_fields:
                    arcpy.AddMessage(f"Chybějící atributy (přeskočeny): {', '.join(missing_fields)}")
                
                # DŮLEŽITÉ: Přidej Layer do dissolve_field aby se zachoval typ SC
                # Vytvoř dissolve_field string (Layer + všechny atributy oddělené středníkem)
                dissolve_fields_list = ["Layer"] + vyska_fields
                dissolve_field_str = ";".join(dissolve_fields_list)
                
                # Vytvoř statistics_fields string (UNIQUE pro každý atribut)
                stats_fields_list = [f"{field} UNIQUE" for field in vyska_fields]
                statistics_fields_str = ";".join(stats_fields_list)
                
                arcpy.management.Dissolve(
                    in_features=sc_with_vyska_fc,
                    out_feature_class=sc_dissolved_vyska_fc,
                    dissolve_field=dissolve_field_str,
                    statistics_fields=statistics_fields_str,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )
                
                arcpy.AddMessage("✓ SC čáry rozpuštěny podle Layer + atributů výšky")
                
                # Vyber pouze segmenty které mají určenou alespoň jednu výšku
                # Vytvoř WHERE klauzuli která kontroluje všechny UNIQUE_* pole
                where_conditions = [f"UNIQUE_{field} IS NOT NULL" for field in vyska_fields]
                where_clause = " OR ".join(where_conditions)
                
                arcpy.management.SelectLayerByAttribute(
                    in_layer_or_view=sc_dissolved_vyska_fc,
                    selection_type="NEW_SELECTION",
                    where_clause=where_clause
                )
                
                # Převeď koncové body těchto segmentů na body
                sc_vertices_name = generate_unique_name(output_gdb, "SC_vertices_temp")
                sc_vertices_fc = os.path.join(output_workspace, sc_vertices_name)
                
                arcpy.management.FeatureVerticesToPoints(
                    in_features=sc_dissolved_vyska_fc,
                    out_feature_class=sc_vertices_fc,
                    point_location="BOTH_ENDS"
                )
                
                # Clear selection
                arcpy.management.SelectLayerByAttribute(
                    in_layer_or_view=sc_dissolved_vyska_fc,
                    selection_type="CLEAR_SELECTION"
                )
                
                # Intersect - získej jen body které se překrývají (kde se mění výška)
                rozhrani_auto_name = generate_unique_name(output_gdb, "rozhrani_auto_temp")
                rozhrani_auto_fc = os.path.join(output_workspace, rozhrani_auto_name)
                
                arcpy.analysis.Intersect(
                    in_features=f"{sc_vertices_fc} #",
                    out_feature_class=rozhrani_auto_fc,
                    join_attributes="ONLY_FID",
                    cluster_tolerance=None,
                    output_type="INPUT"
                )
                
                # Dissolve překrývajících se bodů
                rozhrani_auto_final_name = generate_unique_name(output_gdb, "rozhrani_auto_final_temp")
                rozhrani_auto_final_fc = os.path.join(output_workspace, rozhrani_auto_final_name)
                
                arcpy.management.Dissolve(
                    in_features=rozhrani_auto_fc,
                    out_feature_class=rozhrani_auto_final_fc,
                    dissolve_field=None,
                    statistics_fields=None,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )
                
                auto_points_count = int(arcpy.GetCount_management(rozhrani_auto_final_fc)[0])
                arcpy.AddMessage(f"✓ Vygenerováno {auto_points_count} automatických bodů rozhraní")
                
                # Sloučení CAD rozhraní + automatická rozhraní
                rozhrani_all_name = generate_unique_name(output_gdb, "rozhrani_body_all_temp")
                rozhrani_body_all = os.path.join(output_workspace, rozhrani_all_name)
                
                if rozhrani_body_cad:
                    arcpy.management.Merge(
                        inputs=[rozhrani_body_cad, rozhrani_auto_final_fc],
                        output=rozhrani_body_all
                    )
                    total_rozhrani = int(arcpy.GetCount_management(rozhrani_body_all)[0])
                    arcpy.AddMessage(f"✓ Celkem bodů rozhraní: {total_rozhrani} (CAD + automatické)")
                else:
                    arcpy.CopyFeatures_management(rozhrani_auto_final_fc, rozhrani_body_all)
                    arcpy.AddMessage(f"✓ Celkem bodů rozhraní: {auto_points_count} (pouze automatické)")
                
                # Cleanup
                arcpy.Delete_management(dissolved_for_auto_fc)  # Dočasné dissolved pro auto rozhraní
                arcpy.Delete_management(sc_with_vyska_fc)
                arcpy.Delete_management(sc_dissolved_vyska_fc)
                arcpy.Delete_management(sc_vertices_fc)
                arcpy.Delete_management(rozhrani_auto_fc)
                arcpy.Delete_management(rozhrani_auto_final_fc)
                if rozhrani_body_cad:
                    arcpy.Delete_management(rozhrani_body_cad)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při generování automatických rozhraní: {e}")
                # Fallback - použij jen CAD rozhraní
                if rozhrani_body_cad:
                    rozhrani_body_all = rozhrani_body_cad
        
        # KROK 6: Řezání stavebních čar pomocí všech bodů rozhraní
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("Krok 6: Řezání stavebních čar pomocí rozhraní")
        arcpy.AddMessage("=" * 60)
        
        sc_rozdelene_fc = None
        if rozhrani_body_all and merged_fc and arcpy.Exists(rozhrani_body_all) and arcpy.Exists(merged_fc):
            try:
                # DEBUG: Info před splitováním
                merged_count = int(arcpy.GetCount_management(merged_fc)[0])
                rozhrani_count = int(arcpy.GetCount_management(rozhrani_body_all)[0])
                arcpy.AddMessage(f"DEBUG - Vstup do SplitLineAtPoint:")
                arcpy.AddMessage(f"  SC linie: {merged_count} prvků")
                arcpy.AddMessage(f"  Body rozhraní: {rozhrani_count} bodů")
                
                # DEBUG: Extent check
                merged_extent = arcpy.Describe(merged_fc).extent
                rozhrani_extent = arcpy.Describe(rozhrani_body_all).extent
                arcpy.AddMessage(f"  SC extent: X({merged_extent.XMin:.2f} - {merged_extent.XMax:.2f}), Y({merged_extent.YMin:.2f} - {merged_extent.YMax:.2f})")
                arcpy.AddMessage(f"  Rozhraní extent: X({rozhrani_extent.XMin:.2f} - {rozhrani_extent.XMax:.2f}), Y({rozhrani_extent.YMin:.2f} - {rozhrani_extent.YMax:.2f})")
                
                # DEBUG: Zkontroluj vzdálenost několika bodů rozhraní od SC linií
                arcpy.AddMessage("DEBUG - Měření vzdáleností bodů rozhraní od SC...")
                test_distances = []
                with arcpy.da.SearchCursor(rozhrani_body_all, ["SHAPE@", "OID@"]) as point_cursor:
                    for i, point_row in enumerate(point_cursor):
                        if i >= 5:  # Test jen prvních 5
                            break
                        point_geom = point_row[0]
                        point_oid = point_row[1]
                        
                        # Najdi nejbližší SC linii
                        nearest_dist = float('inf')
                        with arcpy.da.SearchCursor(merged_fc, ["SHAPE@"]) as line_cursor:
                            for line_row in line_cursor:
                                line_geom = line_row[0]
                                dist = point_geom.distanceTo(line_geom)
                                if dist < nearest_dist:
                                    nearest_dist = dist
                        
                        test_distances.append(nearest_dist)
                        arcpy.AddMessage(f"  Bod rozhraní OID={point_oid}: vzdálenost od SC = {nearest_dist:.4f}m")
                
                if test_distances:
                    arcpy.AddMessage(f"  Min: {min(test_distances):.4f}m, Max: {max(test_distances):.4f}m, Avg: {sum(test_distances)/len(test_distances):.4f}m")
                    arcpy.AddMessage(f"  Search radius: 0.3m (budou použity body do 30cm od linie)")
                
                # Split Line At Point NA PŮVODNÍCH LINIÍCH (merged_fc)
                # NE na dissolved - to by změnilo geometrii!
                sc_rozdelene_name = generate_unique_name(output_gdb, "SC_rozdelene_temp")
                sc_rozdelene_fc = os.path.join(output_workspace, sc_rozdelene_name)
                
                arcpy.AddMessage("DEBUG - Spouštím SplitLineAtPoint...")
                arcpy.management.SplitLineAtPoint(
                    in_features=merged_fc,  # PŮVODNÍ linie, NE dissolved!
                    point_features=rozhrani_body_all,
                    out_feature_class=sc_rozdelene_fc,
                    search_radius="0.3 Meters"  # 30cm tolerance (stejně jako snap)
                )
                
                split_count = int(arcpy.GetCount_management(sc_rozdelene_fc)[0])
                arcpy.AddMessage(f"DEBUG - Výstup SplitLineAtPoint: {split_count} segmentů (původně {merged_count})")
                arcpy.AddMessage(f"✓ Původní SC linie rozděleny na {split_count} segmentů podle rozhraní")
                
                # DEBUG: Pokud žádné rozdělení, varování
                if split_count == merged_count:
                    arcpy.AddWarning("⚠ VAROVÁNÍ: Počet segmentů se nezměnil - SplitLineAtPoint nic nenarezal!")
                    arcpy.AddWarning("   Možné příčiny:")
                    arcpy.AddWarning("   1. Body rozhraní jsou dále než 30cm od SC linií")
                    arcpy.AddWarning("   2. Souřadnicové systémy se neshodují")
                    arcpy.AddWarning("   3. Geometrie není validní")
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při řezání stavebních čar: {e}")
        
        # KROK 7: PŘESKOČENO - není potřeba cleanup
        # SplitLineAtPoint na původních liniích nevytváří false rozhraní
        # Cleanup by mohl spojit i segmenty které MAJÍ být rozdělené
        arcpy.AddMessage("Krok 7: Cleanup přeskočen (není potřeba pro původní linie)")
        arcpy.AddMessage(f"  Zachováno všech {int(arcpy.GetCount_management(sc_rozdelene_fc)[0])} segmentů po SplitLineAtPoint")
        
        # KROK 8: Spatial Join pro připojení atributů z dynamických bloků (kruhů)
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("Krok 8: Připojení atributů z dynamických bloků")
        arcpy.AddMessage("=" * 60)
        
        vyskova_regulace_fc = None
        if sc_rozdelene_fc and circles_vr_na_linii and arcpy.Exists(sc_rozdelene_fc) and arcpy.Exists(circles_vr_na_linii):
            try:
                # Převeď kruhy na centrody (středy) - eliminuje problém překrývání
                circles_centroids_name = generate_unique_name(output_gdb, "VR_circles_centroids_temp")
                circles_centroids_fc = os.path.join(output_workspace, circles_centroids_name)
                
                arcpy.management.FeatureToPoint(
                    in_features=circles_vr_na_linii,
                    out_feature_class=circles_centroids_fc,
                    point_location="INSIDE"  # Centroid uvnitř polygonu
                )
                
                centroids_count = int(arcpy.GetCount_management(circles_centroids_fc)[0])
                arcpy.AddMessage(f"✓ Vytvořeno {centroids_count} centroidů z kruhů")
                
                # DEBUG: Zkontroluj jaká pole mají kruhy a centroidy
                arcpy.AddMessage("DEBUG - Kontrola polí v kruzích a centroidech...")
                circle_fields_list = [f.name for f in arcpy.ListFields(circles_vr_na_linii) if f.type not in ["OID", "Geometry"]]
                centroid_fields_list = [f.name for f in arcpy.ListFields(circles_centroids_fc) if f.type not in ["OID", "Geometry"]]
                arcpy.AddMessage(f"  Pole v kruzích ({len(circle_fields_list)}): {', '.join(circle_fields_list[:10])}")
                arcpy.AddMessage(f"  Pole v centroidech ({len(centroid_fields_list)}): {', '.join(centroid_fields_list[:10])}")
                
                # DEBUG: Zkontroluj hodnoty atributů v prvních 3 kruzích
                arcpy.AddMessage("DEBUG - Kontrola hodnot atributů v prvních 3 kruzích...")
                test_attrs = ["RIMSA_MIN", "VYSKA_VB", "NP_MIN", "VYSKA_MAX"]
                existing_test_attrs = [a for a in test_attrs if a in circle_fields_list]
                
                if existing_test_attrs:
                    with arcpy.da.SearchCursor(circles_vr_na_linii, ["OID@"] + existing_test_attrs) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 3:
                                break
                            attr_values = ", ".join([f"{attr}={row[j+1]}" for j, attr in enumerate(existing_test_attrs)])
                            arcpy.AddMessage(f"  Kruh OID={row[0]}: {attr_values}")
                
                # DEBUG: Zkontroluj hodnoty atributů v prvních 3 centroidech
                arcpy.AddMessage("DEBUG - Kontrola hodnot atributů v prvních 3 centroidech...")
                if existing_test_attrs:
                    with arcpy.da.SearchCursor(circles_centroids_fc, ["OID@"] + existing_test_attrs) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 3:
                                break
                            attr_values = ", ".join([f"{attr}={row[j+1]}" for j, attr in enumerate(existing_test_attrs)])
                            arcpy.AddMessage(f"  Centroid OID={row[0]}: {attr_values}")
                
                # DEBUG: Zkontroluj extent centroidů vs SC
                centroid_extent = arcpy.Describe(circles_centroids_fc).extent
                sc_extent = arcpy.Describe(sc_rozdelene_fc).extent
                arcpy.AddMessage(f"DEBUG - Centroid extent: X({centroid_extent.XMin:.2f} - {centroid_extent.XMax:.2f}), Y({centroid_extent.YMin:.2f} - {centroid_extent.YMax:.2f})")
                arcpy.AddMessage(f"DEBUG - SC extent: X({sc_extent.XMin:.2f} - {sc_extent.XMax:.2f}), Y({sc_extent.YMin:.2f} - {sc_extent.YMax:.2f})")
                
                # DEBUG: Zjisti minimální vzdálenost mezi centroidem a SC linií
                arcpy.AddMessage("DEBUG - Měření vzdáleností centroidů od SC linií...")
                min_distance = float('inf')
                max_distance = 0
                distances = []
                
                with arcpy.da.SearchCursor(circles_centroids_fc, ["SHAPE@", "OID@"]) as cent_cursor:
                    for i, cent_row in enumerate(cent_cursor):
                        if i >= 5:  # Kontroluj jen prvních 5 centroidů
                            break
                        centroid_geom = cent_row[0]
                        centroid_oid = cent_row[1]
                        
                        # Najdi nejbližší SC linii
                        nearest_dist = float('inf')
                        with arcpy.da.SearchCursor(sc_rozdelene_fc, ["SHAPE@"]) as sc_cursor:
                            for sc_row in sc_cursor:
                                sc_geom = sc_row[0]
                                dist = centroid_geom.distanceTo(sc_geom)
                                if dist < nearest_dist:
                                    nearest_dist = dist
                        
                        distances.append(nearest_dist)
                        if nearest_dist < min_distance:
                            min_distance = nearest_dist
                        if nearest_dist > max_distance:
                            max_distance = nearest_dist
                        
                        arcpy.AddMessage(f"  Centroid OID={centroid_oid}: nejbližší SC = {nearest_dist:.2f}m")
                
                if distances:
                    avg_distance = sum(distances) / len(distances)
                    arcpy.AddMessage(f"DEBUG - Vzdálenosti (prvních 5): min={min_distance:.2f}m, max={max_distance:.2f}m, avg={avg_distance:.2f}m")
                
                # Získat všechna pole z kruhů
                circle_fields = [field.name for field in arcpy.ListFields(circles_centroids_fc) 
                                if field.type not in ["OID", "Geometry"] and field.name.upper() not in ["SHAPE_LENGTH", "OBJECTID"]]
                
                # Vytvoř field mapping - zachovej všechna pole
                field_mappings = arcpy.FieldMappings()
                field_mappings.addTable(sc_rozdelene_fc)
                field_mappings.addTable(circles_centroids_fc)
                
                # Spatial Join - připoj atributy od NEJBLIŽŠÍHO centroidu
                vyskova_regulace_sj_name = generate_unique_name(output_gdb, "VyskovaRegulace_SJ_temp")
                vyskova_regulace_sj_fc = os.path.join(output_workspace, vyskova_regulace_sj_name)
                
                arcpy.analysis.SpatialJoin(
                    target_features=sc_rozdelene_fc,
                    join_features=circles_centroids_fc,
                    out_feature_class=vyskova_regulace_sj_fc,
                    join_operation="JOIN_ONE_TO_ONE",  # Jeden segment = jeden nejbližší kruh
                    join_type="KEEP_ALL",
                    field_mapping=field_mappings,
                    match_option="CLOSEST",  # Najdi nejbližší centroid
                    search_radius=""  # Bez limitu vzdálenosti - vždy najde nejbližší
                )
                
                arcpy.AddMessage("✓ Atributy připojeny od nejbližších centroidů kruhů")
                
                # DEBUG: Zkontroluj kolik segmentů má přiřazené atributy
                arcpy.AddMessage("DEBUG - Kontrola přiřazených atributů po Spatial Join...")
                null_count = 0
                notnull_count = 0
                
                # Použij první atribut výšky který existuje
                test_field = None
                for field in ["RIMSA_MIN", "VYSKA_VB", "NP_MIN", "VYSKA_MAX"]:
                    if field in [f.name for f in arcpy.ListFields(vyskova_regulace_sj_fc)]:
                        test_field = field
                        break
                
                if test_field:
                    with arcpy.da.SearchCursor(vyskova_regulace_sj_fc, [test_field]) as cursor:
                        for row in cursor:
                            if row[0] is None:
                                null_count += 1
                            else:
                                notnull_count += 1
                    
                    arcpy.AddMessage(f"DEBUG - Segmenty s atributy: {notnull_count}, bez atributů: {null_count}")
                    arcpy.AddMessage(f"DEBUG - Test pole: {test_field}")
                else:
                    arcpy.AddWarning("DEBUG - Žádné pole výšky nenalezeno pro test!")
                
                # Připojit původní atributy ze stavebních čar (Layer, typ SC atd.)
                if merged_fc_original and arcpy.Exists(merged_fc_original):
                    arcpy.AddMessage("Připojování původních atributů ze SC...")
                    
                    # Vytvoř mapu FID -> Layer z původních SC
                    layer_map = {}
                    with arcpy.da.SearchCursor(merged_fc_original, ["OID@", "Layer"]) as cursor:
                        for row in cursor:
                            layer_map[row[0]] = row[1]
                    
                    # Přidej pole SC_Layer do výsledné vrstvy
                    arcpy.management.AddField(
                        in_table=vyskova_regulace_sj_fc,
                        field_name="SC_Layer",
                        field_type="TEXT",
                        field_length=255
                    )
                    
                    # Přidej další užitečná pole z původních SC pokud existují
                    sc_fields = [f.name for f in arcpy.ListFields(merged_fc_original)]
                    useful_fields = ["OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO", "DOK_NAZEV"]
                    
                    for field_name in useful_fields:
                        if field_name in sc_fields:
                            field_obj = [f for f in arcpy.ListFields(merged_fc_original) if f.name == field_name][0]
                            arcpy.management.AddField(
                                in_table=vyskova_regulace_sj_fc,
                                field_name=f"SC_{field_name}",
                                field_type=field_obj.type,
                                field_length=field_obj.length if hasattr(field_obj, 'length') else None
                            )
                    
                    # Přenést hodnoty pomocí TARGET_FID
                    update_fields = ["TARGET_FID", "SC_Layer"] + [f"SC_{f}" for f in useful_fields if f in sc_fields]
                    
                    with arcpy.da.UpdateCursor(vyskova_regulace_sj_fc, update_fields) as cursor:
                        for row in cursor:
                            target_fid = row[0]
                            if target_fid in layer_map:
                                # Načti hodnoty z původní SC
                                with arcpy.da.SearchCursor(merged_fc_original, ["OID@"] + useful_fields, 
                                                          where_clause=f"OBJECTID = {target_fid}") as sc_cursor:
                                    for sc_row in sc_cursor:
                                        row[1] = layer_map[target_fid]  # SC_Layer
                                        # Ostatní pole
                                        for i, field_name in enumerate(useful_fields):
                                            if field_name in sc_fields:
                                                field_idx = update_fields.index(f"SC_{field_name}")
                                                row[field_idx] = sc_row[i + 1]
                                        cursor.updateRow(row)
                                        break
                    
                    arcpy.AddMessage("✓ Původní atributy SC připojeny")
                
                # Cleanup
                arcpy.Delete_management(circles_centroids_fc)
                
                # KROK 9: Vytvoření finální vrstvy (již bez konfliktů díky CLOSEST)
                arcpy.AddMessage("Krok 9: Vytvoření finální vrstvy...")
                
                vyskova_regulace_name = generate_unique_name(output_gdb, "VyskovaRegulaceNaLinii_l")
                vyskova_regulace_fc = os.path.join(output_workspace, vyskova_regulace_name)
                
                # VŠECHNY možné atributy výšky (požadavek 4 - i když nejsou vyplnené)
                possible_vyska_fields = ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "VYSKA_VB_D", 
                                        "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "ID_LOKAL"]
                
                # Zjisti které atributy skutečně existují v vyskova_regulace_sj_fc
                existing_fields = [field.name for field in arcpy.ListFields(vyskova_regulace_sj_fc)]
                
                arcpy.AddMessage(f"Zpracování atributů: {len(possible_vyska_fields)} možných atributů VR")
                
                # Vytvoř statistics_fields string (FIRST pro každý atribut - i NULL)
                stats_fields_list = []
                for field in possible_vyska_fields:
                    if field in existing_fields:
                        stats_fields_list.append(f"{field} FIRST")
                
                # Přidej SC_Layer a další SC atributy do statistik aby přežily Dissolve
                sc_attribute_fields = ["SC_Layer", "SC_OZNACENI", "SC_NAZEV_BLOK", "SC_DRUH_UP", "SC_DRUH_INFO"]
                for sc_field in sc_attribute_fields:
                    if sc_field in existing_fields:
                        stats_fields_list.append(f"{sc_field} FIRST")
                
                statistics_fields_str = ";".join(stats_fields_list)
                
                arcpy.management.Dissolve(
                    in_features=vyskova_regulace_sj_fc,
                    out_feature_class=vyskova_regulace_fc,
                    dissolve_field="TARGET_FID",
                    statistics_fields=statistics_fields_str,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )
                
                # POŽADAVEK 3: Přejmenuj pole - odstraň FIRST_ prefix
                arcpy.AddMessage("Přejmenování polí (odstranění FIRST_ prefixu)...")
                fields_to_rename = []
                for field in arcpy.ListFields(vyskova_regulace_fc):
                    if field.name.startswith("FIRST_"):
                        new_name = field.name.replace("FIRST_", "")
                        fields_to_rename.append((field.name, new_name))
                
                for old_name, new_name in fields_to_rename:
                    try:
                        arcpy.management.AlterField(
                            in_table=vyskova_regulace_fc,
                            field=old_name,
                            new_field_name=new_name,
                            new_field_alias=new_name
                        )
                    except Exception as e:
                        arcpy.AddWarning(f"  Nelze přejmenovat {old_name} → {new_name}: {e}")
                
                arcpy.AddMessage(f"✓ Přejmenováno {len(fields_to_rename)} polí")
                
                # Zjisti které atributy VR skutečně existují (po přejmenování)
                existing_fields_after_rename = [field.name for field in arcpy.ListFields(vyskova_regulace_fc)]
                vyska_fields_exist = [field for field in possible_vyska_fields if field in existing_fields_after_rename]
                
                # Kontrola segmentů bez přiřazených atributů
                if vyska_fields_exist:
                    where_conditions = []
                    for field in vyska_fields_exist:
                        # Po přejmenování pole už nemá FIRST_
                        where_conditions.append(f"{field} IS NULL")
                    where_clause = " AND ".join(where_conditions)  # Všechny atributy NULL = žádný kruh v dosahu
                    
                    arcpy.management.SelectLayerByAttribute(
                        in_layer_or_view=vyskova_regulace_fc,
                        selection_type="NEW_SELECTION",
                        where_clause=where_clause
                    )
                    
                    # Kontrola počtu segmentů bez atributů
                    selection_count = int(arcpy.GetCount_management(vyskova_regulace_fc)[0])
                else:
                    # Pokud nejsou žádné atributy VR, přeskoč kontrolu
                    arcpy.AddMessage("Přeskakuji kontrolu NULL hodnot - žádné atributy VR nenalezeny")
                    selection_count = 0
                
                if selection_count > 0:
                    # Export segmentů bez atributů
                    vyskova_regulace_errors_name = generate_unique_name(output_gdb, "VyskovaRegulaceNaLinii_l_Errors")
                    vyskova_regulace_errors_fc = os.path.join(output_workspace, vyskova_regulace_errors_name)
                    
                    arcpy.conversion.ExportFeatures(
                        in_features=vyskova_regulace_fc,
                        out_features=vyskova_regulace_errors_fc
                    )
                    
                    arcpy.AddWarning(f"⚠ Nalezeno {selection_count} segmentů BEZ přiřazených atributů")
                    arcpy.AddWarning(f"   (žádný kruh v dosahu 50m)")
                    arcpy.AddWarning(f"   Zkontroluj vrstvu: {vyskova_regulace_errors_name}")
                    arcpy.AddMessage("")
                    arcpy.AddMessage("MOŽNÁ ŘEŠENÍ:")
                    arcpy.AddMessage("1. Zkontroluj v CAD že kruhy (302210_BL_VR_na_linii) pokrývají všechny SC")
                    arcpy.AddMessage("2. Ověř že kruhy jsou umístěny blízko stavebních čar (< 50m)")
                    arcpy.AddMessage("3. Případně zvyš search_radius v kódu")
                else:
                    arcpy.AddMessage("✓ Všechny segmenty mají přiřazené atributy od kruhů")
                
                arcpy.AddMessage("=" * 60)
                arcpy.AddMessage("")
                
                # Clear selection
                arcpy.management.SelectLayerByAttribute(
                    in_layer_or_view=vyskova_regulace_fc,
                    selection_type="CLEAR_SELECTION"
                )
                
                total_count = int(arcpy.GetCount_management(vyskova_regulace_fc)[0])
                arcpy.AddMessage(f"✓ Vytvořena finální vrstva výškové regulace: {vyskova_regulace_name}")
                arcpy.AddMessage(f"   Celkem segmentů: {total_count}")
                
                # Rozděl finální vrstvu podle typu stavební čáry (FIRST_SC_Layer obsahuje původní Layer)
                arcpy.AddMessage("")
                arcpy.AddMessage("Rozdělení podle typu stavební čáry...")
                
                # Zkontroluj které pole obsahuje Layer info
                field_names = [f.name for f in arcpy.ListFields(vyskova_regulace_fc)]
                layer_field = None
                
                # Po přejmenování hledej SC_Layer (už bez FIRST_)
                if "SC_Layer" in field_names:
                    layer_field = "SC_Layer"
                else:
                    for fname in field_names:
                        if "Layer" in fname.upper() and "SC" in fname.upper():
                            layer_field = fname
                            break
                
                if layer_field:
                    arcpy.AddMessage(f"Používám pole: {layer_field}")
                    
                    # DEBUG: Zjisti jaké hodnoty jsou v layer_field
                    unique_values = set()
                    with arcpy.da.SearchCursor(vyskova_regulace_fc, [layer_field]) as cursor:
                        for row in cursor:
                            if row[0]:
                                unique_values.add(row[0])
                    
                    arcpy.AddMessage(f"Unikátní hodnoty v {layer_field}: {unique_values}")
                    
                    # POŽADAVEK 2: Dynamické vytvoření vrstev podle VŠECH Layer hodnot v datech
                    # Filtruj jen stavební čáry (začínají 3011xx)
                    
                    # Vytvoř feature layer pro selekci
                    temp_layer = "vyskova_regulace_temp_layer"
                    arcpy.management.MakeFeatureLayer(vyskova_regulace_fc, temp_layer)
                    
                    created_layers = []
                    for layer_value in sorted(unique_values):
                        # Přeskoč NULL/prázdné hodnoty a vrstvy které NEZAČÍNAJÍ na 3011
                        if not layer_value or not layer_value.startswith("3011"):
                            continue
                        
                        # Název výstupní vrstvy = Z + název Layer (např. Z301110_PL_SC_uzavrena)
                        output_base_name = f"Z{layer_value}"
                        
                        # Select podle Layer hodnoty
                        where_clause = f"{layer_field} = '{layer_value}'"
                        
                        arcpy.management.SelectLayerByAttribute(
                            in_layer_or_view=temp_layer,
                            selection_type="NEW_SELECTION",
                            where_clause=where_clause
                        )
                        
                        count = int(arcpy.GetCount_management(temp_layer)[0])
                        if count > 0:
                            # Název vrstvy: Z + Layer hodnota (např. Z301110_PL_SC_uzavrena)
                            output_name = generate_unique_name(output_gdb, output_base_name)
                            output_fc = os.path.join(output_workspace, output_name)
                            
                            arcpy.conversion.ExportFeatures(
                                in_features=temp_layer,
                                out_features=output_fc
                            )
                            
                            arcpy.AddMessage(f"✓ {layer_value}: {output_name} ({count} segmentů)")
                            created_layers.append((output_name, count))
                        else:
                            arcpy.AddMessage(f"  {layer_value}: 0 segmentů (nevytvořeno)")
                    
                    # Clear selection a smaž temp layer
                    arcpy.management.SelectLayerByAttribute(
                        in_layer_or_view=temp_layer,
                        selection_type="CLEAR_SELECTION"
                    )
                    arcpy.Delete_management(temp_layer)
                    
                    # Smaž původní sloučenou vrstvu (už máme rozdělené)
                    arcpy.Delete_management(vyskova_regulace_fc)
                    
                else:
                    arcpy.AddWarning(f"⚠ Pole Layer nenalezeno - vrstva nebude rozdělena podle typu SC")
                    arcpy.AddWarning(f"   Dostupná pole: {', '.join(field_names[:10])}")
                
                # Cleanup dočasných vrstev
                arcpy.Delete_management(vyskova_regulace_sj_fc)
                if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
                    arcpy.Delete_management(rozhrani_body_all)
                if sc_rozdelene_fc and arcpy.Exists(sc_rozdelene_fc):
                    arcpy.Delete_management(sc_rozdelene_fc)
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při připojování atributů nebo identifikaci chyb: {e}")

        # Pokud nebyly nalezeny kruhy VR na linii, zkus přidat VR na bod
        if not circles_vr_na_linii and circles_vr_na_bod:
            arcpy.AddWarning("VR na linii nebyla nalezena - použity pouze kruhy VR na bod")
            # TODO: Implementovat logiku pro VR na bod pokud je to potřeba
        
        # FINÁLNÍ ZPRACOVÁNÍ
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("FINÁLNÍ ZPRACOVÁNÍ - DOKONČENO")
        arcpy.AddMessage("=" * 60)
        
        # Výpis finálních vrstev
        arcpy.env.workspace = output_workspace
        final_vr_fcs = arcpy.ListFeatureClasses("VyskovaRegulace*")
        
        if final_vr_fcs:
            arcpy.AddMessage(f"✓ Vytvořeny výsledné vrstvy výškové regulace:")
            for final_fc in sorted(final_vr_fcs):
                count = int(arcpy.GetCount_management(os.path.join(output_workspace, final_fc))[0])
                arcpy.AddMessage(f"  - {final_fc}: {count} prvků")
        
        # Výpis kruhů
        circle_fcs = arcpy.ListFeatureClasses("*circles*")
        if circle_fcs:
            arcpy.AddMessage(f"✓ Vytvořeny vrstvy kruhů (dynamických bloků):")
            for circle_fc in sorted(circle_fcs):
                count = int(arcpy.GetCount_management(os.path.join(output_workspace, circle_fc))[0])
                arcpy.AddMessage(f"  - {circle_fc}: {count} prvků")

        arcpy.AddMessage(f"Hotovo! Exportováno {exported_count} vrstev z CAD.")
        arcpy.AddMessage("✓ Zpracování výškové regulace dokončeno pomocí metody bez centerline")