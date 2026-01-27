# -*- coding: utf-8 -*-
import arcpy
import os

# Defaultní vrstvy pro MADASPRU project
DEFAULT_LAYERS = [
    "302110_BL_VR_na_bod",
    "302210_BL_VR_na_linii",
    "302211_PL_VR_na_linii_rozhrani"
]

def flatten_to_2d(input_fc, output_fc):
    """Převede 3D geometrie na 2D (odstraní Z-souřadnice)
    
    CAD data často mají různé Z-hodnoty, což způsobuje problémy
    při spatial operacích (Near, Intersect, SpatialJoin).
    Tato funkce vytvoří kopii bez Z-souřadnic.
    """
    # Získej spatial reference
    desc = arcpy.Describe(input_fc)
    sr = desc.spatialReference
    
    # Vytvoř prázdnou feature class
    arcpy.management.CreateFeatureclass(
        out_path=os.path.dirname(output_fc),
        out_name=os.path.basename(output_fc),
        geometry_type=desc.shapeType,
        template=input_fc,
        has_m="DISABLED",
        has_z="DISABLED",  # Klíčové - bez Z
        spatial_reference=sr
    )
    
    # Kopíruj features s 2D geometrií
    fields = [f.name for f in arcpy.ListFields(input_fc) 
              if f.type not in ["OID", "Geometry"] and f.name.upper() not in ["SHAPE_LENGTH", "SHAPE_AREA"]]
    
    with arcpy.da.SearchCursor(input_fc, ["SHAPE@"] + fields) as s_cursor:
        with arcpy.da.InsertCursor(output_fc, ["SHAPE@"] + fields) as i_cursor:
            for row in s_cursor:
                geom = row[0]
                if geom is not None:
                    # Vytvoř 2D verzi geometrie
                    if geom.type == "point":
                        new_geom = arcpy.PointGeometry(arcpy.Point(geom.centroid.X, geom.centroid.Y), sr)
                    elif geom.type == "polyline":
                        parts = []
                        for part in geom:
                            points = [arcpy.Point(p.X, p.Y) for p in part if p is not None]
                            parts.append(arcpy.Array(points))
                        new_geom = arcpy.Polyline(arcpy.Array(parts), sr)
                    elif geom.type == "polygon":
                        parts = []
                        for part in geom:
                            points = [arcpy.Point(p.X, p.Y) for p in part if p is not None]
                            parts.append(arcpy.Array(points))
                        new_geom = arcpy.Polygon(arcpy.Array(parts), sr)
                    else:
                        new_geom = geom
                    
                    i_cursor.insertRow([new_geom] + list(row[1:]))
    
    return output_fc

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
        
        # Zpracování VR na linii vrstvy - POUŽITÍ POLYLINE KRUHŮ S ATRIBUTY Z POINT
        # DŮLEŽITÉ: Polyline kruhy protínají SC (pro INTERSECT), atributy jsou v Point (středy bloků)
        # Musíme propojit kruhy s atributy přes Handle pole
        circles_vr_na_linii = None
        point_vr_na_linii = None  # Body s atributy z dynamických bloků
        
        if vr_na_linii_layer and arcpy.Exists(vr_na_linii_layer):
            try:
                arcpy.AddMessage("Krok 4: Zpracování VR na linii - kruhy + atributy z Point")
                
                # Export Point feature class (dynamic block insertion points WITH attributes)
                layer_name = "302210_BL_VR_na_linii"
                
                if out_prefix:
                    point_name = f"{out_prefix}{layer_name}_POINT"
                else:
                    point_name = f"PL_{layer_name}_POINT"
                
                point_name = generate_unique_name(output_gdb, point_name)
                point_vr_na_linii = os.path.join(output_workspace, point_name)
                
                # Export Point z CAD
                arcpy.env.workspace = input_cad
                field_delimited = arcpy.AddFieldDelimiters("Point", "Layer")
                
                arcpy.FeatureClassToFeatureClass_conversion(
                    in_features="Point",
                    out_path=output_workspace,
                    out_name=point_name,
                    where_clause=f"{field_delimited} = '{layer_name}'"
                )
                
                point_count = int(arcpy.GetCount_management(point_vr_na_linii)[0])
                arcpy.AddMessage(f"✓ Exportováno {point_count} Point prvků s atributy")
                
                # DEBUG: Zkontroluj pole a hodnoty
                point_fields = [f.name for f in arcpy.ListFields(point_vr_na_linii)]
                arcpy.AddMessage(f"DEBUG - Point pole ({len(point_fields)}): {', '.join([f for f in point_fields if not f.startswith('Shape')])[:200]}...")
                
                # DEBUG: Zkontroluj hodnoty atributů
                test_attrs = ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "NP_MIN", "VYSKA_MAX", "RefName"]
                existing_attrs = [a for a in test_attrs if a in point_fields]
                
                if existing_attrs:
                    arcpy.AddMessage(f"DEBUG - Nalezené atributy VR: {', '.join(existing_attrs)}")
                    with arcpy.da.SearchCursor(point_vr_na_linii, ["OID@"] + existing_attrs) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 3:
                                break
                            vals = ", ".join([f"{existing_attrs[j]}={row[j+1]}" for j in range(len(existing_attrs))])
                            arcpy.AddMessage(f"  Point OID={row[0]}: {vals}")
                else:
                    arcpy.AddWarning("  ⚠ Žádné atributy VR nebyly nalezeny v Point!")
                
                # NOVÁ LOGIKA: Zpracování Polyline kruhů a propojení s atributy z Point
                # Kruhy jsou v Polyline a PROTÍNAJÍ stavební čáry
                # Point body jsou STŘEDY bloků a obsahují atributy
                
                arcpy.AddMessage("Krok 4b: Zpracování Polyline kruhů pro VR na linii")
                
                # Multipart to Singlepart pro Polyline kruhy
                if out_prefix:
                    singlepart_name = f"{out_prefix}302210_VR_linii_singlepart_LN"
                else:
                    singlepart_name = "PL_302210_VR_linii_singlepart_LN"
                
                singlepart_name = generate_unique_name(output_gdb, singlepart_name)
                singlepart_fc = os.path.join(output_workspace, singlepart_name)
                
                arcpy.management.MultipartToSinglepart(vr_na_linii_layer, singlepart_fc)
                
                # Filtrování pouze uzavřených linií (kruhy)
                if out_prefix:
                    circles_name = f"{out_prefix}302210_VR_linii_circles_LN"
                else:
                    circles_name = "PL_302210_BL_VR_na_linii_circles"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                circles_fc_temp = os.path.join(output_workspace, circles_name)
                
                # Vytvoření prázdné kopie pro kruhy
                arcpy.management.CreateFeatureclass(
                    out_path=output_workspace,
                    out_name=circles_name.split(os.sep)[-1],
                    geometry_type="POLYLINE",
                    template=singlepart_fc,
                    spatial_reference=output_sr
                )
                
                # Kopírování pouze uzavřených linií (kruhů)
                circles_count = 0
                field_names = [field.name for field in arcpy.ListFields(singlepart_fc) 
                              if field.type != "OID" and field.name.upper() != "OBJECTID"]
                
                with arcpy.da.SearchCursor(singlepart_fc, ["SHAPE@"] + field_names) as search_cursor:
                    with arcpy.da.InsertCursor(circles_fc_temp, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                arcpy.AddMessage(f"✓ Nalezeno {circles_count} uzavřených linií (kruhů) pro VR na linii")
                
                # Smazání dočasné singlepart vrstvy
                arcpy.Delete_management(singlepart_fc)
                
                # PROPOJENÍ ATRIBUTŮ Z POINT DO KRUHŮ
                # Kruhy a Point mají RŮZNÉ Handle (různé entity v dynamickém bloku)
                # Proto používáme PROSTOROVÉ propojení - centroid kruhu CLOSEST k Point
                arcpy.AddMessage("Krok 4c: Propojení atributů z Point do kruhů (prostorově)")
                
                circle_fields = [f.name for f in arcpy.ListFields(circles_fc_temp)]
                point_fields_list = [f.name for f in arcpy.ListFields(point_vr_na_linii)]
                
                # Najdi atributy VR které chceme přenést
                vr_attrs_to_copy = []
                for attr in ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "VYSKA_VB_D", 
                            "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "ID_LOKAL"]:
                    if attr in point_fields_list:
                        vr_attrs_to_copy.append(attr)
                
                arcpy.AddMessage(f"  Atributy k přenosu: {', '.join(vr_attrs_to_copy)}")
                
                # Vytvoř centroidy z kruhů
                arcpy.AddMessage("  Vytvářím centroidy z kruhů...")
                circles_centroids_name = generate_unique_name(output_gdb, "circles_centroids_temp")
                circles_centroids_fc = os.path.join(output_workspace, circles_centroids_name)
                
                arcpy.management.FeatureToPoint(
                    in_features=circles_fc_temp,
                    out_feature_class=circles_centroids_fc,
                    point_location="INSIDE"  # Střed kruhu
                )
                
                centroids_count = int(arcpy.GetCount_management(circles_centroids_fc)[0])
                arcpy.AddMessage(f"  Vytvořeno {centroids_count} centroidů z kruhů")
                
                # DEBUG: Zkontroluj vzdálenosti centroidů od Point
                arcpy.AddMessage("  DEBUG - Měření vzdáleností centroidů od Point...")
                with arcpy.da.SearchCursor(circles_centroids_fc, ["SHAPE@", "OID@"]) as cent_cursor:
                    for i, cent_row in enumerate(cent_cursor):
                        if i >= 3:
                            break
                        cent_geom = cent_row[0]
                        cent_oid = cent_row[1]
                        
                        nearest_dist = float('inf')
                        with arcpy.da.SearchCursor(point_vr_na_linii, ["SHAPE@"]) as pt_cursor:
                            for pt_row in pt_cursor:
                                dist = cent_geom.distanceTo(pt_row[0])
                                if dist < nearest_dist:
                                    nearest_dist = dist
                        
                        arcpy.AddMessage(f"    Centroid OID={cent_oid}: nejbližší Point = {nearest_dist:.2f}m")
                
                # Spatial Join centroidů s Point - CLOSEST bez limitu
                centroids_with_attrs_name = generate_unique_name(output_gdb, "centroids_with_attrs_temp")
                centroids_with_attrs_fc = os.path.join(output_workspace, centroids_with_attrs_name)
                
                field_mappings = arcpy.FieldMappings()
                field_mappings.addTable(circles_centroids_fc)
                field_mappings.addTable(point_vr_na_linii)
                
                arcpy.analysis.SpatialJoin(
                    target_features=circles_centroids_fc,
                    join_features=point_vr_na_linii,
                    out_feature_class=centroids_with_attrs_fc,
                    join_operation="JOIN_ONE_TO_ONE",
                    join_type="KEEP_ALL",
                    field_mapping=field_mappings,
                    match_option="CLOSEST",
                    search_radius=""  # Bez limitu - vždy najde nejbližší
                )
                
                arcpy.AddMessage("  ✓ Centroidy propojeny s nejbližšími Point")
                
                # DEBUG: Zkontroluj hodnoty v centroidech po SJ
                arcpy.AddMessage("  DEBUG - Kontrola atributů v centroidech po propojení:")
                centroid_sj_fields = [f.name for f in arcpy.ListFields(centroids_with_attrs_fc)]
                existing_vr_attrs = [a for a in vr_attrs_to_copy if a in centroid_sj_fields]
                
                # Zkontroluj zda existuje ORIG_FID pole
                has_orig_fid = "ORIG_FID" in centroid_sj_fields
                arcpy.AddMessage(f"  DEBUG - ORIG_FID existuje: {has_orig_fid}")
                arcpy.AddMessage(f"  DEBUG - Pole v centroidech: {', '.join(centroid_sj_fields[:15])}")
                
                if existing_vr_attrs:
                    with arcpy.da.SearchCursor(centroids_with_attrs_fc, ["OID@", "ORIG_FID"] + existing_vr_attrs if has_orig_fid else ["OID@"] + existing_vr_attrs) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 5:
                                break
                            if has_orig_fid:
                                vals = ", ".join([f"{existing_vr_attrs[j]}={row[j+2]}" for j in range(len(existing_vr_attrs))])
                                arcpy.AddMessage(f"    Centroid OID={row[0]}, ORIG_FID={row[1]}: {vals}")
                            else:
                                vals = ", ".join([f"{existing_vr_attrs[j]}={row[j+1]}" for j in range(len(existing_vr_attrs))])
                                arcpy.AddMessage(f"    Centroid OID={row[0]}: {vals}")
                
                # Načti atributy z centroidů - použij ORIG_FID jako klíč pro mapování zpět na kruhy
                attr_map = {}
                if has_orig_fid:
                    with arcpy.da.SearchCursor(centroids_with_attrs_fc, ["ORIG_FID"] + existing_vr_attrs) as cursor:
                        for row in cursor:
                            orig_fid = row[0]
                            attr_map[orig_fid] = {existing_vr_attrs[i]: row[i+1] for i in range(len(existing_vr_attrs))}
                    arcpy.AddMessage(f"  DEBUG - Načteno {len(attr_map)} záznamů do attr_map (klíč=ORIG_FID)")
                    arcpy.AddMessage(f"  DEBUG - Klíče v attr_map: {list(attr_map.keys())[:10]}")
                else:
                    # Fallback - použij OID jako klíč (předpokládá 1:1 korespondenci)
                    with arcpy.da.SearchCursor(centroids_with_attrs_fc, ["OID@"] + existing_vr_attrs) as cursor:
                        for row in cursor:
                            oid = row[0]
                            attr_map[oid] = {existing_vr_attrs[i]: row[i+1] for i in range(len(existing_vr_attrs))}
                    arcpy.AddMessage(f"  DEBUG - Načteno {len(attr_map)} záznamů do attr_map (klíč=OID)")
                
                # Přidej pole do kruhů
                for attr in existing_vr_attrs:
                    if attr not in circle_fields:
                        for f in arcpy.ListFields(centroids_with_attrs_fc):
                            if f.name == attr:
                                arcpy.management.AddField(
                                    in_table=circles_fc_temp,
                                    field_name=attr,
                                    field_type=f.type,
                                    field_length=f.length if hasattr(f, 'length') and f.length else None
                                )
                                break
                
                # DEBUG: Zkontroluj OID v kruzích
                circle_oids = []
                with arcpy.da.SearchCursor(circles_fc_temp, ["OID@"]) as cursor:
                    for row in cursor:
                        circle_oids.append(row[0])
                arcpy.AddMessage(f"  DEBUG - OID v kruzích: {circle_oids[:10]}")
                
                # Aktualizuj kruhy
                matched_count = 0
                unmatched_oids = []
                with arcpy.da.UpdateCursor(circles_fc_temp, ["OID@"] + existing_vr_attrs) as cursor:
                    for row in cursor:
                        oid = row[0]
                        if oid in attr_map:
                            has_value = False
                            for i, attr in enumerate(existing_vr_attrs):
                                val = attr_map[oid].get(attr)
                                row[i+1] = val
                                if val is not None and val != 0 and val != "":
                                    has_value = True
                            cursor.updateRow(row)
                            if has_value:
                                matched_count += 1
                        else:
                            unmatched_oids.append(oid)
                
                if unmatched_oids:
                    arcpy.AddMessage(f"  DEBUG - Nepárované OID kruhů: {unmatched_oids[:10]}")
                
                arcpy.AddMessage(f"✓ Atributy přeneseny do {matched_count}/{circles_count} kruhů (prostorově)")
                
                if matched_count < circles_count:
                    arcpy.AddWarning(f"⚠ {circles_count - matched_count} kruhů má prázdné/nulové atributy")
                
                # Cleanup
                arcpy.Delete_management(circles_centroids_fc)
                arcpy.Delete_management(centroids_with_attrs_fc)
                
                # Nastav circles_vr_na_linii na kruhy S ATRIBUTY
                circles_vr_na_linii = circles_fc_temp
                
                # DEBUG: Zkontroluj hodnoty atributů v kruzích
                arcpy.AddMessage("DEBUG - Kontrola atributů v kruzích po propojení:")
                check_attrs = [a for a in vr_attrs_to_copy if a in [f.name for f in arcpy.ListFields(circles_vr_na_linii)]][:5]
                if check_attrs:
                    with arcpy.da.SearchCursor(circles_vr_na_linii, ["OID@"] + check_attrs) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 4:
                                break
                            vals = ", ".join([f"{check_attrs[j]}={row[j+1]}" for j in range(len(check_attrs))])
                            arcpy.AddMessage(f"  Kruh OID={row[0]}: {vals}")
                
                # DEBUG: Zkontroluj zda kruhy PROTÍNAJÍ SC (nebo SC prochází SKRZ kruh)
                # DŮLEŽITÉ: Používáme 2D vzdálenost (bez Z-souřadnic) protože CAD data mají různé elevace
                arcpy.AddMessage("DEBUG - Kontrola zda kruhy protínají SC linie (2D)...")
                intersect_count = 0
                close_count = 0
                with arcpy.da.SearchCursor(circles_vr_na_linii, ["SHAPE@", "OID@"]) as circle_cursor:
                    for i, circle_row in enumerate(circle_cursor):
                        if i >= 10:
                            break
                        circle_geom = circle_row[0]
                        circle_oid = circle_row[1]
                        
                        # Získej centroid kruhu - 2D bod (bez Z)
                        centroid = circle_geom.centroid
                        sr = circle_geom.spatialReference
                        centroid_point_2d = arcpy.PointGeometry(arcpy.Point(centroid.X, centroid.Y), sr)
                        
                        # Zkus najít SC kterou kruh protíná NEBO která je blízko centroidu
                        found_intersect = False
                        min_distance = float('inf')
                        with arcpy.da.SearchCursor(merged_fc, ["SHAPE@", "OID@"]) as sc_cursor:
                            for sc_row in sc_cursor:
                                sc_geom = sc_row[0]
                                
                                # Vytvoř 2D verzi SC geometrie pro měření
                                sc_parts = []
                                for part in sc_geom:
                                    sc_points = [arcpy.Point(p.X, p.Y) for p in part if p is not None]
                                    sc_parts.append(arcpy.Array(sc_points))
                                sc_geom_2d = arcpy.Polyline(arcpy.Array(sc_parts), sr)
                                
                                # Zkontroluj 2D průnik
                                if not centroid_point_2d.disjoint(sc_geom_2d.buffer(0.5)):  # 0.5m buffer pro kruh
                                    found_intersect = True
                                    break
                                
                                # Měř 2D vzdálenost centroidu od SC
                                dist = centroid_point_2d.distanceTo(sc_geom_2d)
                                if dist < min_distance:
                                    min_distance = dist
                        
                        if found_intersect:
                            intersect_count += 1
                        elif min_distance < 1.0:  # Centroid je do 1m od SC
                            close_count += 1
                            arcpy.AddMessage(f"  Kruh OID={circle_oid}: centroid {min_distance:.2f}m od SC (blízko, 2D)")
                        else:
                            arcpy.AddMessage(f"  ⚠ Kruh OID={circle_oid}: centroid {min_distance:.2f}m od SC (DALEKO, 2D!)")
                
                arcpy.AddMessage(f"DEBUG - {intersect_count}/10 kruhů protíná SC (2D), {close_count}/10 blízko (<1m)")
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při zpracování VR na linii: {e}")
                import traceback
                arcpy.AddWarning(traceback.format_exc())

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
        sc_dissolved_final_fc = None  # Pro uchování dissolved SC
        if rozhrani_body_all and merged_fc and arcpy.Exists(rozhrani_body_all) and arcpy.Exists(merged_fc):
            try:
                # KROK 6a: Dissolve SC podle Layer (jako v notebooku Cell 9)
                # Tím se sloučí všechny segmenty téže SC do jedné linie
                arcpy.AddMessage("Krok 6a: Dissolve SC podle Layer...")
                
                sc_dissolved_final_name = generate_unique_name(output_gdb, "SC_dissolved_final_temp")
                sc_dissolved_final_fc = os.path.join(output_workspace, sc_dissolved_final_name)
                
                arcpy.management.Dissolve(
                    in_features=merged_fc,
                    out_feature_class=sc_dissolved_final_fc,
                    dissolve_field="Layer",  # Zachovej typ SC
                    statistics_fields=None,
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES"
                )
                
                dissolved_count = int(arcpy.GetCount_management(sc_dissolved_final_fc)[0])
                merged_count = int(arcpy.GetCount_management(merged_fc)[0])
                arcpy.AddMessage(f"  Dissolved: {merged_count} → {dissolved_count} linií (sloučeny segmenty téže SC)")
                
                # DEBUG: Info před splitováním
                rozhrani_count = int(arcpy.GetCount_management(rozhrani_body_all)[0])
                arcpy.AddMessage(f"DEBUG - Vstup do SplitLineAtPoint:")
                arcpy.AddMessage(f"  SC linie (dissolved): {dissolved_count} prvků")
                arcpy.AddMessage(f"  Body rozhraní: {rozhrani_count} bodů")
                
                # DEBUG: Extent check
                dissolved_extent = arcpy.Describe(sc_dissolved_final_fc).extent
                rozhrani_extent = arcpy.Describe(rozhrani_body_all).extent
                arcpy.AddMessage(f"  SC extent: X({dissolved_extent.XMin:.2f} - {dissolved_extent.XMax:.2f}), Y({dissolved_extent.YMin:.2f} - {dissolved_extent.YMax:.2f})")
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
                        with arcpy.da.SearchCursor(sc_dissolved_final_fc, ["SHAPE@"]) as line_cursor:
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
                
                # KROK 6b: Split Line At Point NA DISSOLVED LINIÍCH (jako v notebooku Cell 10)
                sc_rozdelene_name = generate_unique_name(output_gdb, "SC_rozdelene_temp")
                sc_rozdelene_fc = os.path.join(output_workspace, sc_rozdelene_name)
                
                arcpy.AddMessage("DEBUG - Spouštím SplitLineAtPoint na dissolved SC...")
                arcpy.management.SplitLineAtPoint(
                    in_features=sc_dissolved_final_fc,  # DISSOLVED linie (jako v notebooku)
                    point_features=rozhrani_body_all,
                    out_feature_class=sc_rozdelene_fc,
                    search_radius="0.3 Meters"  # 30cm tolerance (stejně jako snap)
                )
                
                split_count = int(arcpy.GetCount_management(sc_rozdelene_fc)[0])
                arcpy.AddMessage(f"DEBUG - Výstup SplitLineAtPoint: {split_count} segmentů (z dissolved {dissolved_count})")
                arcpy.AddMessage(f"✓ Dissolved SC linie rozděleny na {split_count} segmentů podle rozhraní")
                
                # DEBUG: Pokud žádné rozdělení, varování
                if split_count == dissolved_count:
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
        
        # KROK 8: Spatial Join pro připojení atributů z dynamických bloků
        # STRATEGIE (jako v notebooku):
        # Kruhy (circles_vr_na_linii) PROTÍNAJÍ segmenty SC
        # Každý segment dostane atributy z kruhu který ho INTERSECT
        # Segmenty bez protínajícího kruhu zůstanou bez atributů (NULL)
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("Krok 8: Připojení atributů z dynamických bloků")
        arcpy.AddMessage("=" * 60)
        
        vyskova_regulace_fc = None
        if sc_rozdelene_fc and circles_vr_na_linii and arcpy.Exists(sc_rozdelene_fc) and arcpy.Exists(circles_vr_na_linii):
            try:
                circles_count = int(arcpy.GetCount_management(circles_vr_na_linii)[0])
                sc_count = int(arcpy.GetCount_management(sc_rozdelene_fc)[0])
                arcpy.AddMessage(f"  Kruhy s atributy: {circles_count}")
                arcpy.AddMessage(f"  Segmenty SC: {sc_count}")
                
                # KROK 8a: Převod na 2D pro správné INTERSECT
                arcpy.AddMessage("Krok 8a: Převod geometrií na 2D...")
                
                # Vytvoř centroidy z kruhů - ty leží přímo na SC liniích
                circles_centroids_name = generate_unique_name(output_gdb, "circles_centroids_temp")
                circles_centroids_fc = os.path.join(output_workspace, circles_centroids_name)
                arcpy.management.FeatureToPoint(
                    in_features=circles_vr_na_linii,
                    out_feature_class=circles_centroids_fc,
                    point_location="INSIDE"
                )
                
                # 2D verze centroidů kruhů
                centroids_2d_name = generate_unique_name(output_gdb, "centroids_2d_temp")
                centroids_2d_fc = os.path.join(output_workspace, centroids_2d_name)
                flatten_to_2d(circles_centroids_fc, centroids_2d_fc)
                
                # 2D verze segmentů SC
                sc_2d_name = generate_unique_name(output_gdb, "sc_2d_temp")
                sc_2d_fc = os.path.join(output_workspace, sc_2d_name)
                flatten_to_2d(sc_rozdelene_fc, sc_2d_fc)
                
                arcpy.AddMessage("  ✓ Geometrie převedeny na 2D")
                
                # DEBUG: Zkontroluj vzdálenosti centroidů od SC v 2D
                arcpy.AddMessage("DEBUG - Měření 2D vzdáleností centroidů od SC segmentů...")
                with arcpy.da.SearchCursor(centroids_2d_fc, ["SHAPE@", "OID@"]) as cent_cursor:
                    for i, cent_row in enumerate(cent_cursor):
                        if i >= 5:
                            break
                        cent_geom = cent_row[0]
                        cent_oid = cent_row[1]
                        min_dist = float('inf')
                        with arcpy.da.SearchCursor(sc_2d_fc, ["SHAPE@"]) as sc_cursor:
                            for sc_row in sc_cursor:
                                dist = cent_geom.distanceTo(sc_row[0])
                                if dist < min_dist:
                                    min_dist = dist
                        arcpy.AddMessage(f"  Centroid OID={cent_oid}: {min_dist:.2f}m od SC (2D)")
                
                # KROK 8b: Spatial Join s WITHIN_A_DISTANCE
                arcpy.AddMessage("Krok 8b: Spatial Join centroidů s SC segmenty...")
                
                # VR atributy
                vr_attrs_for_sj = ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "VYSKA_VB_D", 
                                   "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "ID_LOKAL"]
                
                # Field mapping
                field_mappings = arcpy.FieldMappings()
                
                # Přidej Layer ze SC
                for field in arcpy.ListFields(sc_2d_fc):
                    if field.name == "Layer":
                        fm = arcpy.FieldMap()
                        fm.addInputField(sc_2d_fc, field.name)
                        fm.mergeRule = "First"
                        field_mappings.addFieldMap(fm)
                
                # Přidej VR atributy z centroidů (2D)
                circle_fields = [f.name for f in arcpy.ListFields(centroids_2d_fc)]
                for attr in vr_attrs_for_sj:
                    if attr in circle_fields:
                        fm = arcpy.FieldMap()
                        fm.addInputField(centroids_2d_fc, attr)
                        fm.mergeRule = "First"
                        out_field = fm.outputField
                        out_field.name = attr
                        out_field.aliasName = attr
                        fm.outputField = out_field
                        field_mappings.addFieldMap(fm)
                
                sc_with_attrs_name = generate_unique_name(output_gdb, "sc_with_attrs_temp")
                sc_with_attrs_fc = os.path.join(output_workspace, sc_with_attrs_name)
                
                # Použijeme centroidy (body) místo kruhů (polyline)
                # WITHIN_A_DISTANCE s větším search_radius protože centroid může být mírně od SC
                arcpy.analysis.SpatialJoin(
                    target_features=sc_2d_fc,
                    join_features=centroids_2d_fc,  # Použij centroidy!
                    out_feature_class=sc_with_attrs_fc,
                    join_operation="JOIN_ONE_TO_ONE",
                    join_type="KEEP_ALL",
                    field_mapping=field_mappings,
                    match_option="WITHIN_A_DISTANCE",
                    search_radius="1 Meters"  # Centroid je do 1m od SC
                )
                
                sj_count = int(arcpy.GetCount_management(sc_with_attrs_fc)[0])
                arcpy.AddMessage(f"✓ Spatial Join dokončen: {sj_count} záznamů")
                
                # DEBUG: Zkontroluj přiřazení
                arcpy.AddMessage("DEBUG - Segmenty SC s přiřazenými atributy z centroidů:")
                with arcpy.da.SearchCursor(sc_with_attrs_fc, ["OID@", "Layer", "RIMSA_MAX", "NP_MAX", "Join_Count"]) as cursor:
                    for i, row in enumerate(cursor):
                        if i >= 5:
                            break
                        arcpy.AddMessage(f"  Segment OID={row[0]}, Layer={row[1]}, RIMSA_MAX={row[2]}, NP_MAX={row[3]}, Join_Count={row[4]}")
                
                # Spočítej kolik segmentů má hodnoty vs NULL
                null_count = 0
                with_values_count = 0
                existing_vr_attrs = [a for a in vr_attrs_for_sj if a in circle_fields]
                if existing_vr_attrs:
                    with arcpy.da.SearchCursor(sc_with_attrs_fc, ["Join_Count"]) as cursor:
                        for row in cursor:
                            if row[0] == 0 or row[0] is None:
                                null_count += 1
                            else:
                                with_values_count += 1
                
                arcpy.AddMessage(f"  Segmenty s protínajícím kruhem: {with_values_count}, bez kruhu: {null_count}")
                
                # Cleanup 2D temp vrstvy z Krok 8a/8b
                for temp_fc in [circles_centroids_fc, centroids_2d_fc, sc_2d_fc]:
                    try:
                        if arcpy.Exists(temp_fc):
                            arcpy.Delete_management(temp_fc)
                    except:
                        pass
                
                # KROK 8c: Pro segmenty BEZ přímého kruhu - propagovat atributy z NEJBLIŽŠÍHO kruhu
                # (segmenty mezi rozhraními dostanou atributy z kruhu na téže linii)
                if null_count > 0:
                    arcpy.AddMessage(f"Krok 8c: Propagace atributů na {null_count} segmentů bez přímého kruhu...")
                    
                    # Vytvoř 2D centroidy znovu (byly smazány)
                    circles_centroids_2_name = generate_unique_name(output_gdb, "circles_centroids_2_temp")
                    circles_centroids_2_fc = os.path.join(output_workspace, circles_centroids_2_name)
                    arcpy.management.FeatureToPoint(
                        in_features=circles_vr_na_linii,
                        out_feature_class=circles_centroids_2_fc,
                        point_location="INSIDE"
                    )
                    
                    centroids_2d_2_name = generate_unique_name(output_gdb, "centroids_2d_2_temp")
                    centroids_2d_2_fc = os.path.join(output_workspace, centroids_2d_2_name)
                    flatten_to_2d(circles_centroids_2_fc, centroids_2d_2_fc)
                    
                    # Najdi segmenty bez atributů (Join_Count = 0)
                    segments_without_attrs = []
                    with arcpy.da.SearchCursor(sc_with_attrs_fc, ["OID@", "Join_Count"]) as cursor:
                        for row in cursor:
                            if row[1] == 0 or row[1] is None:
                                segments_without_attrs.append(row[0])
                    
                    arcpy.AddMessage(f"  Segmentů k propagaci: {len(segments_without_attrs)}")
                    
                    # Pro každý segment bez atributů najdi NEJBLIŽŠÍ centroid a přiřaď jeho atributy
                    # Použijeme UpdateCursor
                    update_fields = ["OID@", "SHAPE@", "Join_Count"] + [a for a in vr_attrs_for_sj if a in circle_fields]
                    
                    # Načti atributy ze všech centroidů do paměti
                    centroid_data = []
                    centroid_fields = ["SHAPE@"] + [a for a in vr_attrs_for_sj if a in [f.name for f in arcpy.ListFields(centroids_2d_2_fc)]]
                    with arcpy.da.SearchCursor(centroids_2d_2_fc, centroid_fields) as cursor:
                        for row in cursor:
                            geom = row[0]
                            attrs = {vr_attrs_for_sj[i]: row[i+1] for i in range(len(centroid_fields)-1) if i < len(vr_attrs_for_sj)}
                            centroid_data.append((geom, attrs))
                    
                    arcpy.AddMessage(f"  Načteno {len(centroid_data)} centroidů pro propagaci")
                    
                    # Aktualizuj segmenty bez atributů
                    propagated_count = 0
                    with arcpy.da.UpdateCursor(sc_with_attrs_fc, update_fields) as cursor:
                        for row in cursor:
                            oid = row[0]
                            if oid in segments_without_attrs:
                                segment_geom = row[1]
                                
                                # Najdi nejbližší centroid
                                min_dist = float('inf')
                                nearest_attrs = None
                                for cent_geom, cent_attrs in centroid_data:
                                    dist = segment_geom.distanceTo(cent_geom)
                                    if dist < min_dist:
                                        min_dist = dist
                                        nearest_attrs = cent_attrs
                                
                                if nearest_attrs:
                                    # Přiřaď atributy z nejbližšího centroidu
                                    for i, attr in enumerate(vr_attrs_for_sj):
                                        if attr in circle_fields and attr in nearest_attrs:
                                            row[3 + list(vr_attrs_for_sj).index(attr)] = nearest_attrs[attr]
                                    row[2] = -1  # Označení že jde o propagované atributy
                                    cursor.updateRow(row)
                                    propagated_count += 1
                    
                    arcpy.AddMessage(f"✓ Propagováno {propagated_count} segmentů z nejbližšího kruhu")
                    
                    # Cleanup
                    for temp_fc in [circles_centroids_2_fc, centroids_2d_2_fc]:
                        try:
                            if arcpy.Exists(temp_fc):
                                arcpy.Delete_management(temp_fc)
                        except:
                            pass
                
                # Použij sc_with_attrs_fc jako výstup pro další kroky
                vyskova_regulace_sj_fc = sc_with_attrs_fc
                
                # Připojit původní atributy ze stavebních čar (Layer, typ SC atd.)
                # Layer už máme v sc_rozdelene_fc, jen přejmenujeme na SC_Layer
                arcpy.AddMessage("Připojování původních atributů ze SC...")
                
                # Přidej pole SC_Layer
                sc_fields = [f.name for f in arcpy.ListFields(vyskova_regulace_sj_fc)]
                if "SC_Layer" not in sc_fields and "Layer" in sc_fields:
                    arcpy.management.AddField(
                        in_table=vyskova_regulace_sj_fc,
                        field_name="SC_Layer",
                        field_type="TEXT",
                        field_length=255
                    )
                    # Zkopíruj hodnoty z Layer do SC_Layer
                    with arcpy.da.UpdateCursor(vyskova_regulace_sj_fc, ["Layer", "SC_Layer"]) as cursor:
                        for row in cursor:
                            row[1] = row[0]
                            cursor.updateRow(row)
                
                # Přidej další užitečná pole z původních SC pokud existují
                if merged_fc_original and arcpy.Exists(merged_fc_original):
                    sc_orig_fields = [f.name for f in arcpy.ListFields(merged_fc_original)]
                    useful_fields = ["OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO", "DOK_NAZEV"]
                    
                    for field_name in useful_fields:
                        if field_name in sc_orig_fields:
                            field_obj = [f for f in arcpy.ListFields(merged_fc_original) if f.name == field_name][0]
                            target_field = f"SC_{field_name}"
                            if target_field not in [f.name for f in arcpy.ListFields(vyskova_regulace_sj_fc)]:
                                arcpy.management.AddField(
                                    in_table=vyskova_regulace_sj_fc,
                                    field_name=target_field,
                                    field_type=field_obj.type,
                                    field_length=field_obj.length if hasattr(field_obj, 'length') else None
                                )
                
                arcpy.AddMessage("✓ Původní atributy SC připojeny")
                
                # KROK 9: Vytvoření finální vrstvy - export sc_rozdelene_fc jako finální vrstva
                arcpy.AddMessage("Krok 9: Vytvoření finální vrstvy...")
                
                vyskova_regulace_name = generate_unique_name(output_gdb, "VyskovaRegulaceNaLinii_l")
                vyskova_regulace_fc = os.path.join(output_workspace, vyskova_regulace_name)
                
                # Export jako finální vrstva
                arcpy.conversion.ExportFeatures(
                    in_features=vyskova_regulace_sj_fc,
                    out_features=vyskova_regulace_fc
                )
                
                # Cleanup temp vrstvy
                try:
                    if arcpy.Exists(sc_with_attrs_fc):
                        arcpy.Delete_management(sc_with_attrs_fc)
                except:
                    pass
                
                # VŠECHNY možné atributy výšky
                possible_vyska_fields = ["RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "VYSKA_VB_D", 
                                        "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "ID_LOKAL"]
                
                # Zjisti které atributy skutečně existují
                existing_fields = [field.name for field in arcpy.ListFields(vyskova_regulace_fc)]
                
                arcpy.AddMessage(f"Zpracování atributů: {len(possible_vyska_fields)} možných atributů VR")
                arcpy.AddMessage(f"DEBUG - Pole ve finální vrstvě: {existing_fields[:15]}...")
                
                # DEBUG: Kontrola hodnot
                debug_vr_fields = [f for f in possible_vyska_fields if f in existing_fields]
                if debug_vr_fields:
                    arcpy.AddMessage(f"DEBUG - Kontrola hodnot (první 3 záznamy):")
                    with arcpy.da.SearchCursor(vyskova_regulace_fc, ["OID@"] + debug_vr_fields[:5]) as cursor:
                        for i, row in enumerate(cursor):
                            if i >= 3:
                                break
                            vals = ", ".join([f"{debug_vr_fields[j]}={row[j+1]}" for j in range(min(5, len(debug_vr_fields)))])
                            arcpy.AddMessage(f"  OID={row[0]}: {vals}")
                
                # Zjisti které atributy VR skutečně existují
                existing_fields_final = [field.name for field in arcpy.ListFields(vyskova_regulace_fc)]
                vyska_fields_exist = [field for field in possible_vyska_fields if field in existing_fields_final]
                
                # Kontrola segmentů bez přiřazených atributů
                # Segment je "bez atributů" pokud VŠECHNY VR atributy jsou NULL
                selection_count = 0
                error_oids = []
                
                if vyska_fields_exist:
                    # Použij SearchCursor místo SelectLayerByAttribute (spolehlivější)
                    with arcpy.da.SearchCursor(vyskova_regulace_fc, ["OID@"] + vyska_fields_exist) as cursor:
                        for row in cursor:
                            oid = row[0]
                            # Zkontroluj zda VŠECHNY VR atributy jsou NULL
                            all_null = True
                            for i, val in enumerate(row[1:]):
                                if val is not None and val != "" and val != 0:
                                    all_null = False
                                    break
                            if all_null:
                                error_oids.append(oid)
                    
                    selection_count = len(error_oids)
                    arcpy.AddMessage(f"DEBUG - Kontrola NULL: {selection_count} segmentů má všechny VR atributy NULL/prázdné/0")
                
                if selection_count > 0:
                    # Export segmentů bez atributů
                    vyskova_regulace_errors_name = generate_unique_name(output_gdb, "VyskovaRegulaceNaLinii_l_Errors")
                    vyskova_regulace_errors_fc = os.path.join(output_workspace, vyskova_regulace_errors_name)
                    
                    # Vytvoř where clause pro export
                    oid_list = ",".join([str(oid) for oid in error_oids])
                    where_clause = f"OBJECTID IN ({oid_list})"
                    
                    arcpy.conversion.ExportFeatures(
                        in_features=vyskova_regulace_fc,
                        out_features=vyskova_regulace_errors_fc,
                        where_clause=where_clause
                    )
                    
                    arcpy.AddWarning(f"⚠ Nalezeno {selection_count} segmentů BEZ přiřazených atributů")
                    arcpy.AddWarning(f"   (všechny VR atributy jsou NULL/prázdné)")
                    arcpy.AddWarning(f"   Zkontroluj vrstvu: {vyskova_regulace_errors_name}")
                    arcpy.AddMessage("")
                    arcpy.AddMessage("MOŽNÁ ŘEŠENÍ:")
                    arcpy.AddMessage("1. Zkontroluj v CAD že kruhy (302210_BL_VR_na_linii) pokrývají všechny SC")
                    arcpy.AddMessage("2. Ověř že kruhy jsou umístěny blízko stavebních čar")
                    arcpy.AddMessage("3. Případně přidej search_radius do Spatial Join")
                else:
                    arcpy.AddMessage("✓ Všechny segmenty mají přiřazené atributy z dynamických bloků")
                
                arcpy.AddMessage("=" * 60)
                arcpy.AddMessage("")
                
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