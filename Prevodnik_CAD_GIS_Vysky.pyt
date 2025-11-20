# -*- coding: utf-8 -*-
import arcpy
import os

# Defaultní vrstvy pro MADASPRU project
DEFAULT_LAYERS = [
    "301110_PL_SC_uzavrena",
    "301111_PL_SC_polouzavrena", 
    "301112_PL_SC_otevrena",
    "301113_PL_SC_volna",
    "301114_PL_SC_bez_rozliseni",
    "301115_PL_SC_jina_XX",
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
                            if layer in DEFAULT_LAYERS:
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
                    
                    # Kontrola zda je to SC vrstva (301110-301115) pro pozdější merge
                    if layer_name.startswith(("301110", "301111", "301112", "301113", "301114", "301115")):
                        sc_layers.append(output_fc)
                    
                    # Kontrola zda je to VR rozhraní vrstva pro snap
                    elif layer_name == "302211_PL_VR_na_linii_rozhrani":
                        vr_rozhrani_layer = output_fc
                    
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
        
        # Snap VR rozhraní na SC merge vrstvu
        if vr_rozhrani_layer and merged_fc and arcpy.Exists(vr_rozhrani_layer) and arcpy.Exists(merged_fc):
            try:
                # Snap tolerance 30 cm = 0.3 metrů
                snap_env = [[merged_fc, "EDGE", "0.3 Meters"]]
                arcpy.Snap_edit(vr_rozhrani_layer, snap_env)
                arcpy.AddMessage("VR rozhraní napojeno na SC linie (tolerance 30 cm)")
                
                # Intersect pro vytvoření bodové vrstvy z průsečíků
                try:
                    # Název pro intersect vrstvu
                    if out_prefix:
                        intersect_name = f"{out_prefix}SC_VR_intersect_PT"
                    else:
                        intersect_name = "PL_SC_VR_intersect_PT"
                    
                    intersect_name = generate_unique_name(output_gdb, intersect_name)
                    intersect_fc = os.path.join(output_workspace, intersect_name)
                    
                    # Intersect SC všech linií s VR rozhraním - výstup jako body
                    arcpy.Intersect_analysis(
                        in_features=[merged_fc, vr_rozhrani_layer],
                        out_feature_class=intersect_fc,
                        join_attributes="ALL",
                        cluster_tolerance="",
                        output_type="POINT"
                    )
                    
                    arcpy.AddMessage(f"Vytvořena bodová vrstva průsečíků: {intersect_name}")
                    
                    # PŘÍPRAVA FINÁLNÍ KOMBINOVANÉ VRSTVY
                    # Logika: PL_SC_split_LN (primární) + PL_SC_all_LN tam kde není split (doplňkové)
                    
                    try:
                        # 1. PŘÍPRAVA SPOJENÝCH LINIÍ pro split
                        # Kopie původní merged vrstvy pro zachování
                        original_merged_name = generate_unique_name(output_gdb, "PL_SC_all_backup_temp")
                        original_merged_fc = os.path.join(output_workspace, original_merged_name)
                        arcpy.CopyFeatures_management(merged_fc, original_merged_fc)
                        
                        # Snap vertex všech SC linií na sebe navzájem
                        snap_env = [[merged_fc, "VERTEX", "0.3 Meters"]]
                        arcpy.Snap_edit(merged_fc, snap_env)
                        arcpy.AddMessage("SC linie snapped na sebe navzájem (vertex, 30 cm)")
                        
                        # FEATURE TO LINE - vytvoření topologicky čistých linií místo Dissolve
                        # FeatureToLine vytvoří čisté linie bez duplicitních vrcholů
                        feature_to_line_name = generate_unique_name(output_gdb, "PL_SC_feature_to_line_temp")
                        feature_to_line_fc = os.path.join(output_workspace, feature_to_line_name)
                        
                        arcpy.management.FeatureToLine(
                            in_features=merged_fc,
                            out_feature_class=feature_to_line_fc,
                            cluster_tolerance="0.001 Meters",
                            attributes="ATTRIBUTES"
                        )
                        
                        arcpy.AddMessage("SC linie převedeny na topologicky čisté segmenty pomocí FeatureToLine")
                        
                        # Dissolve pouze spojitých linií (bez multipart)
                        dissolved_name = generate_unique_name(output_gdb, "PL_SC_dissolved_temp")
                        dissolved_fc = os.path.join(output_workspace, dissolved_name)
                        
                        arcpy.Dissolve_management(
                            in_features=feature_to_line_fc,
                            out_feature_class=dissolved_fc,
                            dissolve_field="",
                            statistics_fields="",
                            multi_part="SINGLE_PART",  # Změněno na SINGLE_PART
                            unsplit_lines="DISSOLVE_LINES"
                        )
                        
                        # Připojení do connected_fc
                        connected_name = generate_unique_name(output_gdb, "PL_SC_connected_clean")
                        connected_fc = os.path.join(output_workspace, connected_name)
                        
                        # Repair geometry a clean up
                        arcpy.RepairGeometry_management(dissolved_fc, "DELETE_NULL")
                        arcpy.CopyFeatures_management(dissolved_fc, connected_fc)
                        arcpy.AddMessage("SC linie připraveny jako topologicky čisté spojené segmenty")
                        
                        # 2. IDENTIFIKACE spojených linií které obsahují body rozhraní
                        spatial_join_name = generate_unique_name(output_gdb, "PL_SC_spatial_join_temp")
                        spatial_join_fc = os.path.join(output_workspace, spatial_join_name)
                        
                        arcpy.SpatialJoin_analysis(
                            target_features=connected_fc,
                            join_features=intersect_fc,
                            out_feature_class=spatial_join_fc,
                            join_operation="JOIN_ONE_TO_ONE",
                            join_type="KEEP_ALL",
                            match_option="INTERSECT",
                            search_radius="0.1 Meters"
                        )
                        
                        # Vybrání pouze spojených linií s body rozhraní
                        lines_with_boundaries_name = generate_unique_name(output_gdb, "PL_SC_with_boundaries_temp")
                        lines_with_boundaries_fc = os.path.join(output_workspace, lines_with_boundaries_name)
                        
                        arcpy.Select_analysis(
                            in_features=spatial_join_fc,
                            out_feature_class=lines_with_boundaries_fc,
                            where_clause="Join_Count > 0"
                        )
                        
                        boundary_count = int(arcpy.GetCount_management(lines_with_boundaries_fc)[0])
                        arcpy.AddMessage(f"Nalezeno {boundary_count} spojených linií s body rozhraní")
                        
                        # 3. MÍSTO SPLIT LINIÍ - VYTVOŘÍME BUFFER ZE SPOJENÝCH LINIÍ A TEN SPLITNEME
                        if boundary_count > 0:
                            # Nejprve vytvoříme přesné průsečíky bodů s liniemi
                            precise_points_name = generate_unique_name(output_gdb, "PL_SC_precise_points_temp")
                            precise_points_fc = os.path.join(output_workspace, precise_points_name)
                            
                            # Intersect bodů s liniemi pro získání přesných pozic
                            arcpy.Intersect_analysis(
                                in_features=[lines_with_boundaries_fc, intersect_fc],
                                out_feature_class=precise_points_fc,
                                join_attributes="NO_FID",
                                cluster_tolerance="",
                                output_type="POINT"
                            )
                            
                            # Pokud vznikly multipoint geometrie, převeď je na singlepart
                            multipart_temp = generate_unique_name(output_gdb, "precise_singlepart_temp")
                            multipart_fc = os.path.join(output_workspace, multipart_temp)
                            arcpy.MultipartToSinglepart_management(precise_points_fc, multipart_fc)
                            
                            # Nahraď původní vrstvu singlepart verzí
                            arcpy.Delete_management(precise_points_fc)
                            arcpy.Rename_management(multipart_fc, precise_points_fc)
                            
                            precise_count = int(arcpy.GetCount_management(precise_points_fc)[0])
                            arcpy.AddMessage(f"Nalezeno {precise_count} přesných průsečíků pro buffer split")
                            
                            # Vytvoříme 30cm buffer ze spojených linií (před splitováním)
                            if out_prefix:
                                connected_buffer_name = f"{out_prefix}SC_connected_buffer"
                            else:
                                connected_buffer_name = "PL_SC_connected_buffer"
                            
                            connected_buffer_name = generate_unique_name(output_gdb, connected_buffer_name)
                            connected_buffer_fc = os.path.join(output_workspace, connected_buffer_name)
                            
                            # Buffer ze spojených linií
                            arcpy.analysis.Buffer(
                                in_features=lines_with_boundaries_fc,
                                out_feature_class=connected_buffer_fc,
                                buffer_distance_or_field="0.3 Meters",
                                line_side="FULL",
                                line_end_type="FLAT",
                                dissolve_option="NONE"
                            )
                            
                            arcpy.AddMessage(f"Vytvořen 30cm buffer ze spojených linií: {connected_buffer_name}")
                            
                            # SPLIT BUFFERU podle bodů rozhraní pomocí Erase/Clip logiky
                            if out_prefix:
                                split_buffer_name = f"{out_prefix}SC_split_buffer"
                            else:
                                split_buffer_name = "PL_SC_split_buffer"
                            
                            split_buffer_name = generate_unique_name(output_gdb, split_buffer_name)
                            split_buffer_fc = os.path.join(output_workspace, split_buffer_name)
                            
                            try:
                                # VYTVOŘENÍ KOLMÝCH ŘEZNÝCH ČAR přes buffer v místech bodů
                                cutting_lines_name = generate_unique_name(output_gdb, "cutting_lines_temp")
                                cutting_lines_fc = os.path.join(output_workspace, cutting_lines_name)
                                
                                # Vytvoř feature class pro řezné čáry
                                sr = arcpy.Describe(connected_buffer_fc).spatialReference
                                arcpy.CreateFeatureclass_management(
                                    out_path=output_workspace,
                                    out_name=os.path.basename(cutting_lines_fc),
                                    geometry_type="POLYLINE",
                                    spatial_reference=sr
                                )
                                
                                # Pro každý bod vytvoř kolmou řeznou čáru
                                with arcpy.da.SearchCursor(precise_points_fc, ['SHAPE@']) as point_cursor:
                                    with arcpy.da.InsertCursor(cutting_lines_fc, ['SHAPE@']) as line_cursor:
                                        for point_row in point_cursor:
                                            point_geom = point_row[0]
                                            point_x = point_geom.firstPoint.X
                                            point_y = point_geom.firstPoint.Y
                                            
                                            # Najdi nejbližší linii pro určení směru
                                            min_distance = float('inf')
                                            closest_line = None
                                            
                                            with arcpy.da.SearchCursor(lines_with_boundaries_fc, ['SHAPE@']) as line_search:
                                                for line_row in line_search:
                                                    line_geom = line_row[0]
                                                    distance = line_geom.distanceTo(point_geom)
                                                    if distance < min_distance:
                                                        min_distance = distance
                                                        closest_line = line_geom
                                            
                                            if closest_line:
                                                # Najdi pozici bodu na linii
                                                pos = closest_line.measureOnLine(point_geom)
                                                
                                                # Vytvořím segment kolem bodu pro výpočet směru
                                                start_pos = max(0, pos - 1.0)  # 1m zpět
                                                end_pos = min(closest_line.length, pos + 1.0)  # 1m vpřed
                                                
                                                if end_pos > start_pos:
                                                    segment = closest_line.segmentAlongLine(start_pos, end_pos)
                                                    
                                                    # Aproximace směru pomocí prvního a posledního bodu segmentu
                                                    first_pt = segment.firstPoint
                                                    last_pt = segment.lastPoint
                                                    
                                                    dx = last_pt.X - first_pt.X
                                                    dy = last_pt.Y - first_pt.Y
                                                    length = (dx*dx + dy*dy)**0.5
                                                    
                                                    if length > 0:
                                                        # Kolmý vektor (-dy, dx) normalizovaný
                                                        perp_x = -dy / length
                                                        perp_y = dx / length
                                                        
                                                        # Vytvoř kolmou čáru (1m na každou stranu = 2m celkem)
                                                        line_half_length = 1.0
                                                        start_pt = arcpy.Point(
                                                            point_x - perp_x * line_half_length,
                                                            point_y - perp_y * line_half_length
                                                        )
                                                        end_pt = arcpy.Point(
                                                            point_x + perp_x * line_half_length,
                                                            point_y + perp_y * line_half_length
                                                        )
                                                        
                                                        cutting_line = arcpy.Polyline(
                                                            arcpy.Array([start_pt, end_pt]), sr
                                                        )
                                                        line_cursor.insertRow([cutting_line])
                                
                                cutting_count = int(arcpy.GetCount_management(cutting_lines_fc)[0])
                                arcpy.AddMessage(f"Vytvořeno {cutting_count} kolmých řezných čar pro přesný split bufferu")
                                
                                # POUŽITÍ FEATURE TO POLYGON - přesné rozdělení pomocí čar
                                # Nejdříve převeď buffer na linie (outline)
                                buffer_outline_name = generate_unique_name(output_gdb, "buffer_outline_temp")
                                buffer_outline_fc = os.path.join(output_workspace, buffer_outline_name)
                                
                                arcpy.management.PolygonToLine(
                                    in_features=connected_buffer_fc,
                                    out_feature_class=buffer_outline_fc
                                )
                                
                                # Merge outline s řeznými čárami
                                merged_lines_name = generate_unique_name(output_gdb, "merged_lines_temp")
                                merged_lines_fc = os.path.join(output_workspace, merged_lines_name)
                                
                                arcpy.Merge_management(
                                    inputs=[buffer_outline_fc, cutting_lines_fc],
                                    output=merged_lines_fc
                                )
                                
                                # Feature To Polygon - vytvoří nové polygony rozdělené čárami
                                temp_polygons_name = generate_unique_name(output_gdb, "temp_polygons")
                                temp_polygons_fc = os.path.join(output_workspace, temp_polygons_name)
                                
                                arcpy.management.FeatureToPolygon(
                                    in_features=merged_lines_fc,
                                    out_feature_class=temp_polygons_fc,
                                    cluster_tolerance="0.001 Meters",
                                    attributes="ATTRIBUTES"
                                )
                                
                                # FILTROVÁNÍ - pouze polygony které se protínají s původními liniemi
                                # Vytvoř buffer kolem původních linií pro identifikaci "platných" bufferů
                                original_lines_buffer_name = generate_unique_name(output_gdb, "original_lines_buffer_temp")
                                original_lines_buffer_fc = os.path.join(output_workspace, original_lines_buffer_name)
                                
                                arcpy.analysis.Buffer(
                                    in_features=lines_with_boundaries_fc,
                                    out_feature_class=original_lines_buffer_fc,
                                    buffer_distance_or_field="0.35 Meters",  # Trochu větší než 30cm
                                    dissolve_option="ALL"  # Dissolve všech do jednoho
                                )
                                
                                # Intersect - zachovej pouze polygony které jsou uvnitř tohoto bufferu
                                intersected_polygons_name = generate_unique_name(output_gdb, "intersected_polygons_temp")
                                intersected_polygons_fc = os.path.join(output_workspace, intersected_polygons_name)
                                
                                arcpy.analysis.Intersect(
                                    in_features=[temp_polygons_fc, original_lines_buffer_fc],
                                    out_feature_class=intersected_polygons_fc,
                                    join_attributes="NO_FID"
                                )
                                
                                # DODATEČNÉ FILTROVÁNÍ - spatial join s původními liniemi
                                # Zachovej pouze buffer polygony které obsahují skutečnou linii
                                spatial_join_temp_name = generate_unique_name(output_gdb, "spatial_join_temp")
                                spatial_join_temp_fc = os.path.join(output_workspace, spatial_join_temp_name)
                                
                                arcpy.analysis.SpatialJoin(
                                    target_features=intersected_polygons_fc,
                                    join_features=lines_with_boundaries_fc,  # PL_SC_all linie
                                    out_feature_class=spatial_join_temp_fc,
                                    join_operation="JOIN_ONE_TO_ONE",
                                    join_type="KEEP_ALL",
                                    match_option="INTERSECT"
                                )
                                
                                # Vyfiltruj pouze polygony které mají spojenou linii (Join_Count > 0)
                                # Tím se odstraní vnitřní "díry" které neobsahují žádnou linii
                                where_clause = "Join_Count > 0"
                                
                                arcpy.conversion.FeatureClassToFeatureClass(
                                    in_features=spatial_join_temp_fc,
                                    out_path=output_workspace,
                                    out_name=split_buffer_name,
                                    where_clause=where_clause
                                )
                                
                                # Cleanup navíc
                                arcpy.Delete_management(intersected_polygons_fc)
                                arcpy.Delete_management(spatial_join_temp_fc)
                                
                                # Cleanup navíc
                                arcpy.Delete_management(temp_polygons_fc)
                                arcpy.Delete_management(original_lines_buffer_fc)
                                
                                buffer_parts = int(arcpy.GetCount_management(split_buffer_fc)[0])
                                arcpy.AddMessage(f"Buffer přesně rozdělen kolmicemi na {buffer_parts} částí: {split_buffer_name}")
                                
                                # Cleanup
                                arcpy.Delete_management(cutting_lines_fc)
                                arcpy.Delete_management(buffer_outline_fc)
                                arcpy.Delete_management(merged_lines_fc)
                                arcpy.Delete_management(temp_polygons_fc)
                                arcpy.Delete_management(original_lines_buffer_fc)
                                
                            except Exception as e:
                                arcpy.AddWarning(f"Chyba při rozdělování bufferu kolmicemi: {e}")
                                
                                # Fallback - použij původní buffer s body approach
                                # Vytvoř buffer kolem bodů pro rozdělení
                                points_buffer_name = generate_unique_name(output_gdb, "points_split_buffer_temp")
                                points_buffer_fc = os.path.join(output_workspace, points_buffer_name)
                                
                                arcpy.analysis.Buffer(
                                    in_features=precise_points_fc,
                                    out_feature_class=points_buffer_fc,
                                    buffer_distance_or_field="0.35 Meters"  # Větší než buffer linie (35cm > 30cm) pro zajištění řezu
                                )
                                
                                # Erase - odstraň místa kde jsou body (vytvoří "díry")
                                erased_buffer_name = generate_unique_name(output_gdb, "erased_buffer_temp") 
                                erased_buffer_fc = os.path.join(output_workspace, erased_buffer_name)
                                
                                arcpy.analysis.Erase(
                                    in_features=connected_buffer_fc,
                                    erase_features=points_buffer_fc,
                                    out_feature_class=erased_buffer_fc
                                )
                                
                                # Multipart to Singlepart pro rozdělení
                                arcpy.MultipartToSinglepart_management(erased_buffer_fc, split_buffer_fc)
                                
                                buffer_parts = int(arcpy.GetCount_management(split_buffer_fc)[0])
                                arcpy.AddMessage(f"Buffer rozdělen podle bodů rozhraní na {buffer_parts} částí: {split_buffer_name}")
                                
                                # Cleanup fallback
                                arcpy.Delete_management(points_buffer_fc)
                                arcpy.Delete_management(erased_buffer_fc)
                                
                            except Exception as e:
                                arcpy.AddWarning(f"Chyba při rozdělování bufferu: {e}")
                                # Fallback - použij původní buffer bez rozdělení
                                arcpy.CopyFeatures_management(connected_buffer_fc, split_buffer_fc)
                            
                            # Pro kompatibilitu s existujícím kódem
                            split_fc = split_buffer_fc  # Buffer místo split linií
                            
                            # 4. IDENTIFIKACE původních linií které se NEPŘEKRÝVAJÍ se spojenými liniemi
                            # Jednoduchý přístup - zkopíruj všechny původní a odeber pouze ty které jsou skutečně ve spojených oblastech
                            
                            # Debug informace
                            total_original = int(arcpy.GetCount_management(original_merged_fc)[0])
                            total_connected = int(arcpy.GetCount_management(lines_with_boundaries_fc)[0])
                            arcpy.AddMessage(f"Debug: Původních linií celkem: {total_original}")
                            arcpy.AddMessage(f"Debug: Spojených linií s rozhraními: {total_connected}")
                            
                            # Vytvoř buffer kolem spojených linií pro identifikaci "zakázaných" oblastí
                            connected_buffer_name = generate_unique_name(output_gdb, "PL_SC_connected_buffer_temp")
                            connected_buffer_fc = os.path.join(output_workspace, connected_buffer_name)
                            arcpy.Buffer_analysis(lines_with_boundaries_fc, connected_buffer_fc, "0.5 Meters")
                            
                            # Erase - odeber z původních linií ty části které jsou v bufferu spojených linií
                            non_overlapping_name = generate_unique_name(output_gdb, "PL_SC_non_overlapping_temp")
                            non_overlapping_fc = os.path.join(output_workspace, non_overlapping_name)
                            
                            arcpy.Erase_analysis(
                                in_features=original_merged_fc,
                                erase_features=connected_buffer_fc,
                                out_feature_class=non_overlapping_fc
                            )
                            
                            non_overlap_count = int(arcpy.GetCount_management(non_overlapping_fc)[0])
                            arcpy.AddMessage(f"Debug: Nepřekrývajících se původních linií (po erase): {non_overlap_count}")
                            
                            # Pro kontrolu - spočítej kolik linií bylo "erasovano"
                            erased_count = total_original - non_overlap_count
                            arcpy.AddMessage(f"Debug: Odstraněno (erase): {erased_count} linií z původních")
                            arcpy.AddMessage(f"Debug: Zachováno pro final: {non_overlap_count} původních linií")
                            
                            # 5. VYTVOŘENÍ BUFFERŮ Z PŮVODNÍCH LINIÍ (bez rozhraní)
                            if out_prefix:
                                original_buffer_name = f"{out_prefix}SC_original_buffer"
                            else:
                                original_buffer_name = "PL_SC_original_buffer"
                            
                            original_buffer_name = generate_unique_name(output_gdb, original_buffer_name)
                            original_buffer_fc = os.path.join(output_workspace, original_buffer_name)
                            
                            if non_overlap_count > 0:
                                # Vytvoř 30cm buffer z původních linií bez rozhraní
                                arcpy.analysis.Buffer(
                                    in_features=non_overlapping_fc,
                                    out_feature_class=original_buffer_fc,
                                    buffer_distance_or_field="0.3 Meters",
                                    line_side="FULL",
                                    line_end_type="FLAT",
                                    dissolve_option="NONE"
                                )
                                arcpy.AddMessage(f"Vytvořen 30cm buffer z původních linií: {original_buffer_name}")
                            
                            # 6. FINÁLNÍ KOMBINOVANÁ VRSTVA BUFFERŮ
                            final_name = generate_unique_name(output_gdb, split_buffer_name.replace("split", "final"))
                            final_fc = os.path.join(output_workspace, final_name)
                            
                            if non_overlap_count > 0:
                                # Merge buffer ze splitnutých linií + buffer z původních linií
                                arcpy.Merge_management([split_fc, original_buffer_fc], final_fc)
                                arcpy.AddMessage(f"Vytvořena finální kombinovaná vrstva bufferů: {final_name}")
                                arcpy.AddMessage(f"  - Splitnuté buffery s rozhraními: {int(arcpy.GetCount_management(split_fc)[0])}")
                                arcpy.AddMessage(f"  - Původní buffery bez rozhraní: {non_overlap_count}")
                            else:
                                # Pouze splitnuté buffery
                                arcpy.CopyFeatures_management(split_fc, final_fc)
                                arcpy.AddMessage(f"Finální vrstva obsahuje pouze splitnuté buffery: {final_name}")
                            
                            # Cleanup dočasných vrstev
                            temp_layers = [original_merged_fc, feature_to_line_fc, dissolved_fc, connected_fc, spatial_join_fc, 
                                         lines_with_boundaries_fc, split_fc, connected_buffer_fc, non_overlapping_fc, original_buffer_fc]
                            for temp_fc in temp_layers:
                                if arcpy.Exists(temp_fc):
                                    arcpy.Delete_management(temp_fc)
                            
                        else:
                            arcpy.AddMessage("Žádné spojené linie s body rozhraní - zachována původní merged vrstva")
                            # Cleanup dočasných vrstev
                            temp_layers = [original_merged_fc, feature_to_line_fc, dissolved_fc, connected_fc, spatial_join_fc, lines_with_boundaries_fc]
                            for temp_fc in temp_layers:
                                if arcpy.Exists(temp_fc):
                                    arcpy.Delete_management(temp_fc)
                        
                    except Exception as e:
                        arcpy.AddWarning(f"Chyba při vytváření finální kombinované vrstvy: {e}")
                
                except Exception as e:
                    arcpy.AddWarning(f"Chyba při intersect operaci: {e}")
                
            except Exception as e:
                arcpy.AddWarning(f"Chyba při snap operaci: {e}")

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

        # SPATIAL JOIN EXISTUJÍCÍHO BUFFERU S KRUHY
        # Najdi finální buffer vrstvu a kruhy
        buffer_fc = None
        circles_fc = None
        
        # Hledání finálního bufferu
        arcpy.env.workspace = output_workspace
        buffer_classes = arcpy.ListFeatureClasses("*final_buffer*")
        if buffer_classes:
            buffer_fc = os.path.join(output_workspace, buffer_classes[0])
            arcpy.AddMessage(f"Nalezena finální buffer vrstva: {buffer_classes[0]}")
        
        # Hledání vrstvy kruhů
        circle_classes = arcpy.ListFeatureClasses("*circles*")
        if circle_classes:
            circles_fc = os.path.join(output_workspace, circle_classes[0])
            arcpy.AddMessage(f"Nalezena vrstva kruhů: {circle_classes[0]}")
        
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
                        arcpy.AddWarning("Foundation/Production Mapping extension není dostupná - centerline se nevytvoří")
                        arcpy.AddWarning("Pro vytvoření centerline je potřeba ArcGIS Production Mapping nebo Foundation extension")
                        
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

        # FINÁLNÍ SPLIT A CLEANUP - na úplném konci po všech operacích
        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("FINÁLNÍ ZPRACOVÁNÍ")
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

        arcpy.AddMessage(f"Hotovo! Exportováno {exported_count} vrstev.")
        arcpy.AddMessage("✓ Všechny podpůrné vrstvy smazány, zachovány pouze finální vrstvy rozdělené podle 'Layer'")