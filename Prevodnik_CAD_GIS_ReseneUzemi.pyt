# -*- coding: utf-8 -*-
import arcpy
import os

def parameter(displayName, name, datatype,
              parameterType='Required',
              direction='Input',
              multiValue=False,
              defaultValue=None):
    """
    Pomocná funkce pro tvorbu parametrů v Python Toolboxu.
    """
    param = arcpy.Parameter(
        displayName=displayName,
        name=name,
        datatype=datatype,
        parameterType=parameterType,
        direction=direction,
        multiValue=multiValue
    )
    if defaultValue is not None:
        param.value = defaultValue
    return param

def get_all_fc_names(gdb_path):
    """
    Projde celou geodatabázi (včetně feature datasetů) a vrátí množinu všech existujících feature class názvů.
    """
    fc_names = set()
    walk = arcpy.da.Walk(gdb_path, datatype="FeatureClass")
    for dirpath, dirnames, filenames in walk:
        for fc in filenames:
            fc_names.add(fc)
    return fc_names

def sanitize_fc_name(name):
    """
    Sanitizuje název feature class podle pravidel ArcGIS:
    - Musí začínat písmem nebo podtržítkem
    - Smí obsahovat písmena, čísla a podtržítka
    - Ostatní znaky se nahradí podtržítkem
    """
    # Nahradit zvláštní znaky podtržítkem
    sanitized = ""
    for char in name:
        if char.isalnum() or char == "_":
            sanitized += char
        else:
            sanitized += "_"
    
    # Pokud začíná číslem, přidat prefix
    if sanitized and sanitized[0].isdigit():
        sanitized = f"Z{sanitized}"
    
    # Pokud je prázdné, použít default
    if not sanitized:
        sanitized = "Layer"
    
    return sanitized

def generate_unique_fc_name(base, workspace):
    """
    Vygeneruje unikátní název feature class v rámci workspace.
    Pokud již jméno existuje, přidá se přípona _1, _2, atd.
    """
    # Sanitizace základního názvu
    base = sanitize_fc_name(base)
    
    existing = get_all_fc_names(workspace)
    unique = base
    counter = 1
    while unique in existing:
        unique = f"{base}_{counter}"
        counter += 1
    return unique

# Globální slovník přípon dle typu FC z CADu
GEOMETRY_SUFFIX = {
    "Point": "PT",
    "Polyline": "LN", 
    "Polygon": "PL",
    "Annotation": "ANN",
    "MultiPatch": "MP"
}

class CadLayer(object):
    """
    Reprezentuje jednu vrstvu z CADu a související geometrii.
    """
    def __init__(self, cad_file, cad_fc, cad_layer):
        self.cad_file = cad_file
        self.cad_fc = cad_fc
        self.name = cad_layer

    def geometry_suffix(self):
        return GEOMETRY_SUFFIX.get(self.cad_fc, "OTH")

    def export(self, output_workspace, new_name=None,
               spatial_ref=None, transform_method=None,
               out_prefix=""):
        """
        Exportuje jednu CAD vrstvu do geodatabáze.
        """
        if not new_name:
            base_name = self.name
            suffix = self.geometry_suffix()
            new_name = f"{base_name}_{suffix}"
        if out_prefix:
            new_name = f"{out_prefix}{new_name}"
        
        output_name = arcpy.ValidateTableName(new_name, output_workspace)
        
        # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
        desc_ws = arcpy.Describe(output_workspace)
        if desc_ws.datatype == "FeatureDataset":
            gdb_path = os.path.dirname(output_workspace)
        else:
            gdb_path = output_workspace
            
        # Zajištění jedinečnosti názvu
        existing_names = get_all_fc_names(gdb_path)
        unique_name = output_name
        counter = 1
        while unique_name in existing_names:
            unique_name = f"{output_name}_{counter}"
            counter += 1
        output_name = unique_name

        fc_path = os.path.join(self.cad_file, self.cad_fc)
        if not arcpy.Exists(fc_path):
            arcpy.AddWarning(f"Feature class '{fc_path}' neexistuje, vrstva '{self.name}' přeskočena.")
            return None
        
        # SQL dotaz pro filtrování vrstvy
        field_delimited = arcpy.AddFieldDelimiters(fc_path, "Layer")
        sql = f"{field_delimited} = '{self.name}'"
        arcpy.AddMessage(f"[export] Vrstva '{self.name}' => SQL: {sql}")
        
        # Kontrola počtu záznamů
        count = 0
        try:
            with arcpy.da.SearchCursor(fc_path, ["OID@"], sql) as cursor:
                for _ in cursor:
                    count += 1
        except Exception as e:
            arcpy.AddWarning(f"[export] Chyba při čtení záznamů: {e}")
            return None
        
        if count == 0:
            arcpy.AddWarning(f"[export] Vrstva '{self.name}' (geom: {self.cad_fc}) nemá záznamy -> přeskočeno.")
            return None
        
        arcpy.AddMessage(f"[export] Nalezeno {count} záznamů pro '{self.name}' ({self.cad_fc}).")
        
        # Export vrstvy
        out_fc = os.path.join(output_workspace, output_name)
        try:
            arcpy.FeatureClassToFeatureClass_conversion(fc_path, output_workspace, output_name, sql)
            arcpy.AddMessage(f"[export] Vrstva '{self.name}' exportována jako '{output_name}'.")
        except Exception as e:
            arcpy.AddWarning(f"[export] Chyba při exportu '{self.name}': {e}")
            return None

        # Definice a reprojekce souřadnicového systému
        if spatial_ref:
            out_fc = self.define_and_project(out_fc, spatial_ref, transform_method)
            
        return out_fc

    def define_and_project(self, fc, spatial_ref, transform_method=None):
        """
        Definuje souřadnicový systém a provede reprojekci pokud je potřeba.
        """
        try:
            desc = arcpy.Describe(fc)
            source_sr = desc.spatialReference
            
            # Pokud zdrojový SR není definován nebo je neznámý, definujeme ho
            if not source_sr or source_sr.name.lower() == "unknown" or source_sr.factoryCode == 0:
                arcpy.AddMessage(f"[export] Definuji SR: {spatial_ref.name}")
                arcpy.DefineProjection_management(fc, spatial_ref)
                source_sr = spatial_ref

            # Kontrola, zda je potřeba reprojekce
            need_reproject = False
            if (source_sr.factoryCode != 0) and (spatial_ref.factoryCode != 0):
                if source_sr.factoryCode != spatial_ref.factoryCode:
                    need_reproject = True
            else:
                if source_sr.exportToString() != spatial_ref.exportToString():
                    need_reproject = True

            if need_reproject:
                out_ws = os.path.dirname(fc)
                base_name = os.path.basename(fc)
                temp_fc = os.path.join(out_ws, base_name + "_prj")
                
                arcpy.AddMessage(f"[export] Reprojekce '{base_name}' -> {spatial_ref.name}")
                
                if transform_method:
                    arcpy.Project_management(fc, temp_fc, spatial_ref, transform_method, source_sr)
                else:
                    arcpy.Project_management(fc, temp_fc, spatial_ref)
                    
                arcpy.Delete_management(fc)
                arcpy.Rename_management(temp_fc, base_name)
                fc = os.path.join(out_ws, base_name)
                
        except Exception as e:
            arcpy.AddWarning(f"[export] Nelze reprojektovat '{fc}': {e}")
            
        return fc


class CadFile(object):
    """
    Reprezentuje CAD soubor a jeho vrstvy.
    """
    def __init__(self, cad_file):
        self.cad_file = cad_file
        self.display_map = self.get_layers()
        self.layer_display_names = sorted(self.display_map.keys())

    def get_layers(self):
        """
        Načte všechny vrstvy z CAD souboru.
        """
        arcpy.env.workspace = self.cad_file
        geometry_types = ["Point", "Polyline", "Polygon", "Annotation", "MultiPatch"]
        result = {}
        
        for fc_type in geometry_types:
            if arcpy.Exists(fc_type):
                try:
                    with arcpy.da.SearchCursor(fc_type, ["Layer"]) as cur:
                        all_lays = [row[0] for row in cur]
                    for lyr in sorted(set(all_lays)):
                        disp_name = f"{lyr} ({fc_type})"
                        result[disp_name] = CadLayer(self.cad_file, fc_type, lyr)
                except Exception as e:
                    arcpy.AddWarning(f"Chyba při načítání '{fc_type}': {e}")
        
        if not result:
            arcpy.AddWarning("[CadFile] Žádné vrstvy v CADu.")
        else:
            arcpy.AddMessage("[CadFile] Nalezené vrstvy: " + ", ".join(result.keys()))
        
        return result

    def export_layers(self, selected_display_names, output_workspace,
                    spatial_ref=None, transform_method=None, out_prefix=""):
        """
        Exportuje vybrané vrstvy do geodatabáze.
        """
        exported_layers = []
        polylines_for_merge = []  # Seznam pro polyline vrstvy určené k merge
        point_layers_for_join = []  # Seznam pro bodové vrstvy určené k spatial join
        resene_point_fc = None  # Bod Resene_uzemi pro speciální zpracování
        vyska_circles_fc = None  # Výškové kruhy pro speciální zpracování
        vyska_rozhrani_fc = None  # Rozhraní výškových kruhů pro split polygonů

        # Pokud nejsou vybrané konkrétní vrstvy, exportujeme všechny
        if not selected_display_names:
            items = self.display_map.items()
        else:
            items = [(dn, self.display_map[dn]) for dn in selected_display_names if dn in self.display_map]

        for disp_name, cad_layer in items:
            # Kontrola, zda se jedná o polyline vrstvy určené pro speciální zpracování
            is_special_polyline = (
                cad_layer.name in ["101110_PL_Resene_uzemi", "200000_PL_Cast_uzemi"] and 
                cad_layer.cad_fc == "Polyline"
            )
            
            # Kontrola, zda se jedná o bodové vrstvy určené pro spatial join
            is_special_point = (
                cad_layer.name in ["202110_BL_Cast_uzemi_UP", "203110_BL_Cast_uzemi_SB", 
                                  "204110_BL_Cast_uzemi_NB", "205110_BL_Cast_uzemi_XB"] and 
                cad_layer.cad_fc == "Point"
            )
            
            # Kontrola pro bod Resene_uzemi (speciální zpracování)
            is_resene_point = (
                cad_layer.name == "101111_BL_Resene_uzemi" and 
                cad_layer.cad_fc == "Point"
            )
            
            # Kontrola pro výškové kruhy (302310_BL_VR_na_plochu)
            is_vyska_circles = (
                cad_layer.name == "302310_BL_VR_na_plochu" and 
                cad_layer.cad_fc == "Polyline"
            )
            
            # Kontrola pro rozhraní výškových kruhů (302311_PL_VR_na_plochu_rozhrani)
            is_vyska_rozhrani = (
                cad_layer.name == "302311_PL_VR_na_plochu_rozhrani" and 
                cad_layer.cad_fc == "Polyline"
            )
            
            if is_special_polyline:
                # Export polyline vrstvy pro pozdější merge
                exported = cad_layer.export(
                    output_workspace,
                    spatial_ref=spatial_ref,
                    transform_method=transform_method,
                    out_prefix=out_prefix
                )
                if exported:
                    polylines_for_merge.append(exported)
                    arcpy.AddMessage(f"[export_layers] Polyline vrstva '{cad_layer.name}' přidána pro merge.")
            elif is_special_point:
                # Export bodové vrstvy pro pozdější spatial join
                exported = cad_layer.export(
                    output_workspace,
                    spatial_ref=spatial_ref,
                    transform_method=transform_method,
                    out_prefix=out_prefix
                )
                if exported:
                    point_layers_for_join.append(exported)
                    arcpy.AddMessage(f"[export_layers] Bodová vrstva '{cad_layer.name}' přidána pro spatial join.")
            elif is_resene_point:
                # Export bodu Resene_uzemi pro speciální zpracování
                exported = cad_layer.export(
                    output_workspace,
                    spatial_ref=spatial_ref,
                    transform_method=transform_method,
                    out_prefix=out_prefix
                )
                if exported:
                    resene_point_fc = exported
                    arcpy.AddMessage(f"[export_layers] Bod Resene_uzemi '{cad_layer.name}' exportován pro speciální zpracování.")
            elif is_vyska_circles:
                # Export výškových kruhů pro speciální zpracování
                exported = cad_layer.export(
                    output_workspace,
                    spatial_ref=spatial_ref,
                    transform_method=transform_method,
                    out_prefix=out_prefix
                )
                if exported:
                    vyska_circles_fc = exported
                    arcpy.AddMessage(f"[export_layers] Výškové kruhy '{cad_layer.name}' exportovány pro speciální zpracování.")
            elif is_vyska_rozhrani:
                # Export rozhraní výškových kruhů pro split polygonů
                exported = cad_layer.export(
                    output_workspace,
                    spatial_ref=spatial_ref,
                    transform_method=transform_method,
                    out_prefix=out_prefix
                )
                if exported:
                    vyska_rozhrani_fc = exported
                    arcpy.AddMessage(f"[export_layers] Rozhraní výškových kruhů '{cad_layer.name}' exportováno pro split polygonů.")
            else:
                # Standardní export ostatních vrstev
                exported = cad_layer.export(
                    output_workspace,
                    spatial_ref=spatial_ref,
                    transform_method=transform_method,
                    out_prefix=out_prefix
                )
                if exported:
                    exported_layers.append(exported)

        # Speciální zpracování polyline vrstev - merge, feature to polygon, integrate
        polygon_fc = None
        if len(polylines_for_merge) >= 1:
            try:
                # Najít linii řešeného území pro novou strategii
                resene_line_fc = None
                for pl_fc in polylines_for_merge:
                    if "101110_PL_Resene_uzemi" in os.path.basename(pl_fc):
                        resene_line_fc = pl_fc
                        break
                
                polygon_fc, main_polygon_fc = self.process_polylines_to_polygon(
                    polylines_for_merge, resene_line_fc, output_workspace, out_prefix, spatial_ref
                )
                if polygon_fc and main_polygon_fc:
                    exported_layers.append(polygon_fc)
                    # main_polygon_fc je pouze dočasný - nebude se ukládat
                    # Zachovat obě původní polyline vrstvy
                    for pl_fc in polylines_for_merge:
                        exported_layers.append(pl_fc)
                        arcpy.AddMessage(f"[export_layers] Zachována polyline vrstva: {os.path.basename(pl_fc)}")
            except Exception as e:
                arcpy.AddError(f"[export_layers] Chyba při zpracování polyline vrstev: {e}")
                # V případě chyby ponecháme původní polyline vrstvy
                exported_layers.extend(polylines_for_merge)

        # Zpracování výškových kruhů - převod na body (centroids)
        # NEPŘIDÁVAT do point_layers_for_join - budou zpracovány samostatně
        vyska_centroids_fc = None
        if vyska_circles_fc:
            try:
                vyska_centroids_fc = self.process_vyska_circles_to_points(
                    vyska_circles_fc, output_workspace, out_prefix, spatial_ref
                )
                if vyska_centroids_fc:
                    arcpy.AddMessage(f"[export_layers] Centroids výškových kruhů připraveny pro samostatný spatial join.")
            except Exception as e:
                arcpy.AddWarning(f"[export_layers] Chyba při zpracování výškových kruhů: {e}")
        
        # Spatial join bodových vrstev k polygonům a analýza (BEZ výškových bodů)
        if polygon_fc and len(point_layers_for_join) > 0:
            try:
                analysis_results = self.perform_spatial_join_analysis(
                    polygon_fc, point_layers_for_join, output_workspace, out_prefix
                )
                if analysis_results:
                    main_analysis_fc = analysis_results[0]  # Resene_uzemi_with_Points
                    
                    # NOVÁ STRATEGIE: Místo snappování používáme už vytvořený hlavní polygon
                    if main_polygon_fc:
                        # Zpracování bodu Resene_uzemi s hlavním polygonem (přídání atributu "bod")
                        if resene_point_fc:
                            updated_main_polygon_fc = self.process_resene_point_with_polygon(
                                main_polygon_fc, resene_point_fc, output_workspace, out_prefix
                            )
                            if updated_main_polygon_fc:
                                # Polygon s atributem "bod" je výsledek
                                exported_layers.append(updated_main_polygon_fc)
                                
                                # Analýza "within" - kontrola zda menší polygony leží v řešeném území
                                self.add_within_analysis(main_analysis_fc, updated_main_polygon_fc, output_workspace, out_prefix)
                        else:
                            # Pokud není bod, použijeme hlavní polygon přímo
                            exported_layers.append(main_polygon_fc)
                            
                            # Analýza "within" i bez bodu
                            self.add_within_analysis(main_analysis_fc, main_polygon_fc, output_workspace, out_prefix)
                    
                    # Smazat původní polygonovou vrstvu, protože máme už tu s body
                    try:
                        arcpy.Delete_management(polygon_fc)
                        arcpy.AddMessage(f"[export_layers] Smazána původní polygonová vrstva: {os.path.basename(polygon_fc)}")
                    except Exception as e:
                        arcpy.AddWarning(f"[export_layers] Nelze smazat původní polygon: {e}")
                    
                    # SPLIT POLYGONŮ podle rozhraní výškových kruhů (pokud existuje)
                    # Musí být PŘED split_analysis_by_layer a PŘED připojením výškových atributů
                    if vyska_rozhrani_fc:
                        try:
                            main_analysis_fc = self.split_polygons_by_vyska_rozhrani(
                                main_analysis_fc, vyska_rozhrani_fc, output_workspace, out_prefix
                            )
                            arcpy.AddMessage("[export_layers] ✓ Polygony rozděleny podle rozhraní výškových kruhů")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Chyba při split polygonů podle rozhraní: {e}")
                    
                    # Split Resene_uzemi_with_Points podle pole Layer
                    split_results = self.split_analysis_by_layer(
                        main_analysis_fc, output_workspace, out_prefix
                    )
                    if split_results:
                        exported_layers.extend(split_results)
                        
                        # SAMOSTATNÝ SPATIAL JOIN VÝŠKOVÝCH BODŮ ke splitnutým polygonům
                        # (po rozdělení, aby se atributy připojily k finálním vrstvám)
                        if vyska_centroids_fc:
                            try:
                                arcpy.AddMessage("[export_layers] Připojuji výškové atributy k finálním polygonům...")
                                for split_fc in split_results:
                                    self.add_vyska_attributes(split_fc, vyska_centroids_fc)
                                arcpy.AddMessage("[export_layers] ✓ Výškové atributy připojeny ke všem finálním polygonům")
                            except Exception as e:
                                arcpy.AddWarning(f"[export_layers] Chyba při připojování výškových atributů: {e}")
                    
                    # Vytvoření chybových polygonů (sloučené polygony s chybami)
                    # 1. Chybový polygon pro špatné body (bez bodu nebo více bodů)
                    error_bod_fc = self.create_error_polygon_bod(
                        main_analysis_fc, output_workspace, out_prefix
                    )
                    if error_bod_fc:
                        exported_layers.append(error_bod_fc)
                    
                    # 2. Chybový polygon pro polygony mimo řešené území
                    error_resene_uzemi_fc = self.create_error_polygon_resene_uzemi(
                        main_analysis_fc, output_workspace, out_prefix
                    )
                    if error_resene_uzemi_fc:
                        exported_layers.append(error_resene_uzemi_fc)
                    
                    # Smazat původní vrstvu s body (nahrazena split výsledky)
                    try:
                        arcpy.Delete_management(main_analysis_fc)
                        arcpy.AddMessage(f"[export_layers] Smazána originální analýza vrstva")
                    except Exception as e:
                        arcpy.AddWarning(f"[export_layers] Nelze smazat analýzu: {e}")
                    
                    # Smazat bodové vrstvy - již se nepoužívají
                    for point_fc in point_layers_for_join:
                        try:
                            arcpy.Delete_management(point_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána bodová vrstva: {os.path.basename(point_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat bodovou vrstvu {os.path.basename(point_fc)}: {e}")
                    
                    # Smazat výškové centroidy - již se nepoužívají
                    if vyska_centroids_fc:
                        try:
                            arcpy.Delete_management(vyska_centroids_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána bodová vrstva výškových centroidů: {os.path.basename(vyska_centroids_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat výškové centroidy: {e}")
                    
                    # Smazat bod Resene_uzemi - již se nepoužívá
                    if resene_point_fc:
                        try:
                            arcpy.Delete_management(resene_point_fc)
                            arcpy.AddMessage(f"[export_layers] Smazán bod Resene_uzemi: {os.path.basename(resene_point_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat bod Resene_uzemi: {e}")
                    
            except Exception as e:
                arcpy.AddError(f"[export_layers] Chyba při spatial join analýze: {e}")
        
        return exported_layers

    def split_polygons_by_vyska_rozhrani(self, polygon_fc, rozhrani_fc, output_workspace, out_prefix):
        """
        Rozdělí polygony podle rozhraní výškových kruhů (302311_PL_VR_na_plochu_rozhrani).
        Proces:
        1. Snap rozhraní k hranám polygonů (tolerance 30 cm)
        2. Polygon to Line (hrany polygonů)
        3. Merge hran + rozhraní
        4. Feature to Polygon (rozdělení)
        5. Spatial join zpět k původním polygonům (přenos atributů)
        """
        try:
            arcpy.AddMessage("[split_polygons_vyska] Začínám rozdělování polygonů podle rozhraní výškových kruhů")
            
            # 1. Snap rozhraní k hranám polygonů (30 cm tolerance)
            arcpy.AddMessage("[split_polygons_vyska] 1. Snap rozhraní k hranám polygonů (30 cm)")
            snap_env = [[polygon_fc, "EDGE", "0.3 Meters"]]
            arcpy.edit.Snap(rozhrani_fc, snap_env)
            
            # 2. Polygon to Line - převod polygonů na linie
            arcpy.AddMessage("[split_polygons_vyska] 2. Převod polygonů na linie")
            polygon_lines_name = generate_unique_fc_name(f"{out_prefix}polygon_edges_temp",
                                                        os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            polygon_lines_fc = os.path.join(output_workspace, polygon_lines_name)
            
            arcpy.management.PolygonToLine(
                in_features=polygon_fc,
                out_feature_class=polygon_lines_fc
            )
            
            # 3. Merge hran polygonů + rozhraní
            arcpy.AddMessage("[split_polygons_vyska] 3. Merge hran + rozhraní")
            merged_lines_name = generate_unique_fc_name(f"{out_prefix}merged_split_lines_temp",
                                                       os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            merged_lines_fc = os.path.join(output_workspace, merged_lines_name)
            
            arcpy.management.Merge(
                inputs=[polygon_lines_fc, rozhrani_fc],
                output=merged_lines_fc
            )
            
            # 4. Feature to Polygon - vytvoření nových rozdělených polygonů
            arcpy.AddMessage("[split_polygons_vyska] 4. Feature to Polygon - rozdělení")
            split_polygons_name = generate_unique_fc_name(f"{out_prefix}split_polygons_temp",
                                                          os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            split_polygons_fc = os.path.join(output_workspace, split_polygons_name)
            
            arcpy.management.FeatureToPolygon(
                in_features=merged_lines_fc,
                out_feature_class=split_polygons_fc,
                cluster_tolerance="0.001 Meters"
            )
            
            split_count = int(arcpy.GetCount_management(split_polygons_fc)[0])
            arcpy.AddMessage(f"[split_polygons_vyska] Vytvořeno {split_count} rozdělených polygonů")
            
            # 5. Spatial Join - přenos atributů z původních polygonů
            arcpy.AddMessage("[split_polygons_vyska] 5. Spatial join - přenos atributů")
            final_split_name = generate_unique_fc_name(os.path.basename(polygon_fc).replace("_temp", ""),
                                                       os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            final_split_fc = os.path.join(output_workspace, final_split_name)
            
            arcpy.analysis.SpatialJoin(
                target_features=split_polygons_fc,
                join_features=polygon_fc,
                out_feature_class=final_split_fc,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="HAVE_THEIR_CENTER_IN"
            )
            
            final_count = int(arcpy.GetCount_management(final_split_fc)[0])
            arcpy.AddMessage(f"[split_polygons_vyska] ✓ Finálních rozdělených polygonů: {final_count}")
            
            # Cleanup dočasných vrstev
            arcpy.Delete_management(polygon_lines_fc)
            arcpy.Delete_management(merged_lines_fc)
            arcpy.Delete_management(split_polygons_fc)
            arcpy.Delete_management(polygon_fc)  # Smazat původní nerozdělenou vrstvu
            
            arcpy.AddMessage(f"[split_polygons_vyska] Výsledná vrstva: {final_split_name}")
            
            return final_split_fc
            
        except Exception as e:
            arcpy.AddError(f"[split_polygons_vyska] Chyba při rozdělování polygonů: {e}")
            return polygon_fc  # V případě chyby vrátit původní

    def add_vyska_attributes(self, polygon_fc, vyska_points_fc):
        """
        Připojí výškové atributy z bodů k polygonům pomocí spatial join.
        Nepřepisuje existující polygony, jen přidává nová pole.
        """
        try:
            arcpy.AddMessage(f"[add_vyska_attributes] Připojuji výškové atributy k: {os.path.basename(polygon_fc)}")
            
            # Vytvoření dočasné vrstvy se spatial join
            temp_join_name = f"temp_vyska_join_{os.path.basename(polygon_fc)}"
            temp_join_fc = os.path.join("in_memory", temp_join_name)
            
            arcpy.analysis.SpatialJoin(
                target_features=polygon_fc,
                join_features=vyska_points_fc,
                out_feature_class=temp_join_fc,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="CONTAINS"
            )
            
            # Seznam výškových atributů k přenosu
            vyska_fields = [
                "OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO", "DOK_NAZEV",
                "RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "PODTYP",
                "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "VYSKA_VB_D"
            ]
            
            # Najít která pole skutečně existují v temp_join
            temp_fields = [f.name for f in arcpy.ListFields(temp_join_fc)]
            fields_to_transfer = []
            
            for field in vyska_fields:
                # Hledat pole s suffixem _1 (z join)
                if f"{field}_1" in temp_fields:
                    fields_to_transfer.append(field)
            
            if not fields_to_transfer:
                arcpy.AddMessage(f"[add_vyska_attributes] Žádné výškové atributy k přenosu")
                arcpy.Delete_management(temp_join_fc)
                return
            
            # Přidat nová pole do původního polygonu (pokud neexistují)
            for field in fields_to_transfer:
                target_field_name = f"VR_{field}"  # Prefix VR_ pro rozlišení od klasifikačních atributů
                
                # Zkontrolovat zda pole už existuje
                existing_fields = [f.name for f in arcpy.ListFields(polygon_fc)]
                if target_field_name not in existing_fields:
                    # Zjistit typ pole ze source
                    source_field = [f for f in arcpy.ListFields(temp_join_fc) if f.name == f"{field}_1"][0]
                    arcpy.AddField_management(
                        polygon_fc,
                        target_field_name,
                        source_field.type,
                        field_length=source_field.length if source_field.type == "String" else None
                    )
            
            # Přenést hodnoty pomocí Update Cursor
            poly_fields = ["OBJECTID"] + [f"VR_{field}" for field in fields_to_transfer]
            temp_fields_to_read = ["TARGET_FID"] + [f"{field}_1" for field in fields_to_transfer]
            
            # Vytvoření mapy hodnot z temp_join
            value_map = {}
            with arcpy.da.SearchCursor(temp_join_fc, temp_fields_to_read) as cursor:
                for row in cursor:
                    target_fid = row[0]
                    values = row[1:]
                    value_map[target_fid] = values
            
            # Aktualizace původních polygonů
            updated_count = 0
            with arcpy.da.UpdateCursor(polygon_fc, poly_fields) as cursor:
                for row in cursor:
                    oid = row[0]
                    if oid in value_map:
                        # Zkopírovat hodnoty
                        for i, value in enumerate(value_map[oid]):
                            row[i + 1] = value
                        cursor.updateRow(row)
                        updated_count += 1
            
            arcpy.AddMessage(f"[add_vyska_attributes] ✓ Aktualizováno {updated_count} polygonů, přeneseno {len(fields_to_transfer)} atributů")
            
            # Cleanup
            arcpy.Delete_management(temp_join_fc)
            
        except Exception as e:
            arcpy.AddWarning(f"[add_vyska_attributes] Chyba: {e}")

    def process_vyska_circles_to_points(self, circles_fc, output_workspace, out_prefix, spatial_ref):
        """
        Zpracuje výškové kruhy (302310_BL_VR_na_plochu):
        1. Multipart to Singlepart (rozdělit vícenásobné geometrie)
        2. Filtrování pouze uzavřených linií (kruhy)
        3. Převod kruhů na body (centroids)
        4. Výsledek: bodová vrstva se středy kruhů + všechny atributy
        """
        arcpy.AddMessage("[process_vyska_circles] Začínám zpracování výškových kruhů.")
        
        try:
            # 1. Multipart to Singlepart
            singlepart_name = generate_unique_fc_name(f"{out_prefix}VR_plochu_singlepart_temp", 
                                                     os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            singlepart_fc = os.path.join(output_workspace, singlepart_name)
            
            arcpy.management.MultipartToSinglepart(circles_fc, singlepart_fc)
            arcpy.AddMessage("[process_vyska_circles] Multipart to Singlepart dokončen")
            
            # 2. Vytvoření prázdné feature class pro kruhy
            circles_only_name = generate_unique_fc_name(f"{out_prefix}302310_VR_circles_LN", 
                                                        os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            circles_only_fc = os.path.join(output_workspace, circles_only_name)
            
            arcpy.management.CreateFeatureclass(
                out_path=output_workspace,
                out_name=os.path.basename(circles_only_fc),
                geometry_type="POLYLINE",
                template=singlepart_fc,
                spatial_reference=spatial_ref
            )
            
            # 3. Kopírování pouze uzavřených linií (kruhy)
            circles_count = 0
            field_names = [field.name for field in arcpy.ListFields(singlepart_fc) 
                          if field.type != "OID" and field.name.upper() != "OBJECTID"]
            
            with arcpy.da.SearchCursor(singlepart_fc, ["SHAPE@"] + field_names) as search_cursor:
                with arcpy.da.InsertCursor(circles_only_fc, ["SHAPE@"] + field_names) as insert_cursor:
                    for row in search_cursor:
                        geometry = row[0]
                        if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                            insert_cursor.insertRow(row)
                            circles_count += 1
            
            arcpy.AddMessage(f"[process_vyska_circles] Nalezeno a zachováno {circles_count} uzavřených linií (kruhů)")
            
            # Smazání dočasné singlepart vrstvy
            arcpy.Delete_management(singlepart_fc)
            
            if circles_count == 0:
                arcpy.AddWarning("[process_vyska_circles] Nebyly nalezeny žádné kruhy - přeskakuji převod na body")
                arcpy.Delete_management(circles_only_fc)
                return None
            
            # 4. Převod kruhů na body (centroids)
            circles_points_name = generate_unique_fc_name(f"{out_prefix}302310_VR_circle_centroids_PT", 
                                                          os.path.dirname(output_workspace) if arcpy.Describe(output_workspace).datatype == "FeatureDataset" else output_workspace)
            circles_points_fc = os.path.join(output_workspace, circles_points_name)
            
            arcpy.management.FeatureToPoint(
                in_features=circles_only_fc,
                out_feature_class=circles_points_fc,
                point_location="INSIDE"  # Centroid uvnitř polygonu
            )
            
            points_count = int(arcpy.GetCount_management(circles_points_fc)[0])
            arcpy.AddMessage(f"[process_vyska_circles] Vytvořeno {points_count} bodů (centroidů kruhů)")
            arcpy.AddMessage(f"[process_vyska_circles] Výsledná bodová vrstva: {circles_points_name}")
            
            # Smazání mezivýsledků (kruhy ponecháme pro případnou kontrolu)
            # arcpy.Delete_management(circles_only_fc)
            
            return circles_points_fc
            
        except Exception as e:
            arcpy.AddError(f"[process_vyska_circles] Chyba při zpracování výškových kruhů: {e}")
            return None

    def process_polylines_to_polygon(self, polyline_fcs, resene_line_fc, output_workspace, out_prefix, spatial_ref):
        """
        Zpracuje polyline vrstvy podle původní strategie + integrate:
        1. Merge VŠECH linií (řešené území + části) → snap → Feature to Polygon → ZAPLNĚNÉ polygony
        2. Samostatná linie řešeného území → Feature to Polygon → hlavní polygon
        3. Merge obou sad polygonů → integrate → oddělení (bez hlavního polygonu)
        Výsledek: zaplněné polygony s přesným napojením + dočasný hlavní polygon pro within analýzu.
        """
        arcpy.AddMessage("[process_polylines_to_polygon] Začínám speciální zpracování polyline vrstev.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # 1. Merge VŠECH polyline vrstev (včetně linie řešeného území)
            merged_name = f"{out_prefix}Merged_Polylines" if out_prefix else "Merged_Polylines"
            merged_fc = os.path.join(output_workspace, generate_unique_fc_name(merged_name, root_gdb))
            
            arcpy.AddMessage(f"[process_polylines_to_polygon] 1. Merge VŠECH polyline vrstev (včetně řešeného území) do: {merged_fc}")
            arcpy.management.Merge(polyline_fcs, merged_fc)  # Všechny včetně resene_line_fc
            
            # 2. Snap linií k sobě navzájem s tolerancí 30 cm pro spojení neuzavřených konců
            arcpy.AddMessage("[process_polylines_to_polygon] 2. Snap linií k hranám (EDGE) - tolerance 30 cm")
            snap_env = [[merged_fc, "EDGE", "0.3 Meters"]]
            arcpy.edit.Snap(merged_fc, snap_env)
            
            # 3. Feature to Polygon z VŠECH mergnutých linií (zaplněný polygon)
            temp_filled_polygons = "in_memory\\temp_filled_polygons"
            
            arcpy.AddMessage(f"[process_polylines_to_polygon] 3. Feature to Polygon ze všech mergnutých linií (zaplněný)")
            arcpy.management.FeatureToPolygon(
                in_features=merged_fc,
                out_feature_class=temp_filled_polygons,
                cluster_tolerance="",
                attributes="ATTRIBUTES"
            )
            
            # 4. Vytvoření polygonu z linie řešeného území (SAMOSTATNĚ pro integrate)
            temp_main_polygon = "in_memory\\temp_main_polygon"
            arcpy.AddMessage(f"[process_polylines_to_polygon] 4. Vytvářím polygon z linie řešeného území (pro integrate)")
            arcpy.management.FeatureToPolygon(
                in_features=resene_line_fc,  # POUZE linie řešeného území
                out_feature_class=temp_main_polygon,
                cluster_tolerance="",
                attributes="ATTRIBUTES"
            )
            
            # 5. Přidání označení pro identifikaci polygonů
            arcpy.management.AddField(temp_filled_polygons, "polygon_type", "TEXT", field_length=20)
            arcpy.management.AddField(temp_main_polygon, "polygon_type", "TEXT", field_length=20)
            
            with arcpy.da.UpdateCursor(temp_filled_polygons, ["polygon_type"]) as cursor:
                for row in cursor:
                    row[0] = "ZAPLNENE_POLYGONY"  # Zaplněné polygony z merged linií
                    cursor.updateRow(row)
                    
            with arcpy.da.UpdateCursor(temp_main_polygon, ["polygon_type"]) as cursor:
                for row in cursor:
                    row[0] = "MAIN_RESENE_UZEMI"  # Hlavní polygon pro integrate
                    cursor.updateRow(row)
            
            # 6. Merge všech polygonů pro společný integrate
            all_polygons_temp = "in_memory\\all_polygons_temp"
            
            arcpy.AddMessage(f"[process_polylines_to_polygon] 5. Merge všech polygonů pro společný integrate")
            arcpy.management.Merge([temp_filled_polygons, temp_main_polygon], all_polygons_temp)
            
            # 7. Integrate na všechny polygony najednou - zaručí správné geometrické napojení
            arcpy.AddMessage("[process_polylines_to_polygon] 6. Integrate všech polygonů s tolerancí 30 cm")
            arcpy.management.Integrate([all_polygons_temp], "0.3 Meters")
            
            # 8. Oddělení finálních polygonů (BEZ hlavního polygonu řešeného území)
            parts_polygon_name = f"{out_prefix}Resene_uzemi_PL" if out_prefix else "Resene_uzemi_PL"
            parts_polygon_fc = os.path.join(output_workspace, generate_unique_fc_name(parts_polygon_name, root_gdb))
            
            arcpy.AddMessage(f"[process_polylines_to_polygon] 7. Oddělení finálních polygonů (bez hlavního řešeného území)")
            arcpy.analysis.Select(
                in_features=all_polygons_temp,
                out_feature_class=parts_polygon_fc,
                where_clause="polygon_type = 'ZAPLNENE_POLYGONY'"
            )
            
            # 9. Oddělení hlavního polygonu řešeného území (dočasně pro analýzu within)
            main_polygon_temp = "in_memory\\main_polygon_integrated"
            
            arcpy.AddMessage(f"[process_polylines_to_polygon] 8. Oddělení hlavního polygonu řešeného území (dočasně)")
            arcpy.analysis.Select(
                in_features=all_polygons_temp,
                out_feature_class=main_polygon_temp,
                where_clause="polygon_type = 'MAIN_RESENE_UZEMI'"
            )
            
            # 10. Vyčištění dočasných dat
            arcpy.Delete_management(merged_fc)
            arcpy.Delete_management(temp_filled_polygons)
            arcpy.Delete_management(temp_main_polygon)
            arcpy.Delete_management(all_polygons_temp)
            
            arcpy.AddMessage(f"[process_polylines_to_polygon] Úspěšně vytvořeny polygonové vrstvy:")
            arcpy.AddMessage(f"[process_polylines_to_polygon] - Finální polygony: {parts_polygon_fc} (zaplněné, integrate napojené)")
            arcpy.AddMessage(f"[process_polylines_to_polygon] - Hlavní řešené území: dočasný (pro within analýzu)")
            
            return parts_polygon_fc, main_polygon_temp
            
        except Exception as e:
            arcpy.AddError(f"[process_polylines_to_polygon] Chyba při zpracování: {e}")
            return None, None

    def perform_spatial_join_analysis(self, polygon_fc, point_fcs, output_workspace, out_prefix):
        """
        Provede spatial join bodových vrstev k polygonům a přidá atribut "bod" s hodnocením.
        """
        arcpy.AddMessage("[perform_spatial_join_analysis] Začínám spatial join analýzu.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # 1. Merge všech bodových vrstev pro analýzu
            merged_points_name = f"{out_prefix}Merged_Points_temp" if out_prefix else "Merged_Points_temp"
            merged_points_fc = os.path.join(output_workspace, generate_unique_fc_name(merged_points_name, root_gdb))
            
            arcpy.AddMessage(f"[perform_spatial_join_analysis] 1. Merge bodových vrstev do: {merged_points_fc}")
            arcpy.management.Merge(point_fcs, merged_points_fc)
            
            # 2. Hlavní Spatial Join s připojením atributů a počítáním
            final_join_name = f"{out_prefix}Resene_uzemi_with_Points" if out_prefix else "Resene_uzemi_with_Points"
            final_join_fc = os.path.join(output_workspace, generate_unique_fc_name(final_join_name, root_gdb))
            
            arcpy.AddMessage(f"[perform_spatial_join_analysis] 2. Hlavní Spatial Join s atributy: {final_join_fc}")
            arcpy.analysis.SpatialJoin(
                target_features=polygon_fc,
                join_features=merged_points_fc,
                out_feature_class=final_join_fc,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="CONTAINS"
            )
            
            # 3. Přidání pole "bod" s hodnocením na základě Join_Count
            arcpy.management.AddField(final_join_fc, "bod", "TEXT", field_length=20)
            
            arcpy.AddMessage("[perform_spatial_join_analysis] 3. Nastavuji hodnocení na základě Join_Count")
            with arcpy.da.UpdateCursor(final_join_fc, ["Join_Count", "bod"]) as cursor:
                for row in cursor:
                    join_count = row[0] if row[0] is not None else 0
                    
                    # Nastavení hodnoty pole "bod" podle skutečného Join_Count
                    if join_count == 0:
                        row[1] = "bez bodu"
                    elif join_count == 1:
                        row[1] = "v pořádku"
                    else:
                        row[1] = "více bodů"
                    
                    cursor.updateRow(row)
            
            # 4. Vyčištění dočasných dat
            arcpy.Delete_management(merged_points_fc)
            
            # 5. Statistiky na základě skutečných Join_Count hodnot
            stats_dict = {"bez bodu": 0, "v pořádku": 0, "více bodů": 0}
            with arcpy.da.SearchCursor(final_join_fc, ["bod"]) as cursor:
                for row in cursor:
                    if row[0] in stats_dict:
                        stats_dict[row[0]] += 1
            
            total_count = sum(stats_dict.values())
            
            arcpy.AddMessage(f"[perform_spatial_join_analysis] Analýza dokončena:")
            arcpy.AddMessage(f"  - Celkem polygonů: {total_count}")
            arcpy.AddMessage(f"  - V pořádku (1 bod): {stats_dict['v pořádku']}")
            arcpy.AddMessage(f"  - Bez bodu: {stats_dict['bez bodu']}")
            arcpy.AddMessage(f"  - Více bodů: {stats_dict['více bodů']}")
            arcpy.AddMessage(f"  - Výsledná vrstva: {os.path.basename(final_join_fc)}")
            
            return [final_join_fc]
            
        except Exception as e:
            arcpy.AddError(f"[perform_spatial_join_analysis] Chyba při analýze: {e}")
            return []

    def snap_resene_line_to_polygon(self, polygon_fc, resene_line_fc, output_workspace, out_prefix):
        """
        Přichytí původní linii Resene_uzemi k hranicím finálního polygonu.
        """
        arcpy.AddMessage("[snap_resene_line_to_polygon] Začínám přichycení linie k polygonu.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # 1. Převést polygon na linie pro snapping
            temp_polygon_lines = "in_memory\\temp_polygon_lines"
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] 1. Převádím polygon na linie pro snapping")
            arcpy.management.PolygonToLine(polygon_fc, temp_polygon_lines)
            
            # 2. Zkopírovat původní linii pro úpravu
            temp_resene_copy = "in_memory\\temp_resene_copy"
            arcpy.management.CopyFeatures(resene_line_fc, temp_resene_copy)
            
            # 2.5. Densifikovat linii pro lepší snap výsledky
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] 2. Densifikuji linii pro lepší snap (každých 5m)")
            arcpy.edit.Densify(temp_resene_copy, "DISTANCE", "5 Meters")
            
            # 3. Snap původní linie k hranicím polygonu - pouze EDGE pro hladké napojení
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] 3. Přichycuji linii k hranicím polygonu (pouze EDGE)")
            
            # Snap k hranám s tolerancí 1m - vytvoří hladké napojení k polygonům
            snap_env = [[temp_polygon_lines, "EDGE", "1 Meters"]]
            arcpy.edit.Snap(temp_resene_copy, snap_env)
            
            # 4. Vrácení dočasné snapped linie (bez uložení do geodatabáze)
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] 4. Snapped linie připravena pro další zpracování")
            
            # 5. Vyčištění dočasných dat (kromě temp_resene_copy, kterou vracíme)
            arcpy.Delete_management(temp_polygon_lines)
            
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] Úspěšně vytvořena dočasná snapped linie s vylepšeným snappováním")
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] - Densifikace: každých 5m")
            arcpy.AddMessage(f"[snap_resene_line_to_polygon] - Snap EDGE: tolerance 1m (pouze hraně pro hladké napojení)")
            
            return temp_resene_copy  # Vrácení dočasné linie místo uložené
            
        except Exception as e:
            arcpy.AddError(f"[snap_resene_line_to_polygon] Chyba při snapping: {e}")
            return None

    def process_resene_point_with_polygon(self, main_polygon_fc, resene_point_fc, output_workspace, out_prefix):
        """
        Zpracuje bod Resene_uzemi s hlavním polygonem - spatial join, vrátí finální polygon s atributem "bod".
        Hlavní polygon je pouze dočasný (in_memory), výsledkem je Resene_uzemi_Polygon_with_Points.
        """
        arcpy.AddMessage("[process_resene_point_with_polygon] Začínám zpracování bodu Resene_uzemi s hlavním polygonem.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # 1. Spatial Join bodu k polygonu
            temp_join = "in_memory\\temp_resene_polygon_join"
            arcpy.AddMessage(f"[process_resene_point_with_polygon] 1. Spatial join bodu k hlavnímu polygonu")
            arcpy.analysis.SpatialJoin(
                target_features=main_polygon_fc,
                join_features=resene_point_fc,
                out_feature_class=temp_join,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="CONTAINS"
            )
            
            # 2. Přidání pole "bod" s hodnocením
            arcpy.management.AddField(temp_join, "bod", "TEXT", field_length=20)
            
            arcpy.AddMessage("[process_resene_point_with_polygon] 2. Nastavuji hodnocení bodu")
            with arcpy.da.UpdateCursor(temp_join, ["Join_Count", "bod"]) as cursor:
                for row in cursor:
                    join_count = row[0] if row[0] is not None else 0
                    
                    if join_count == 0:
                        row[1] = "bez bodu"
                    elif join_count == 1:
                        row[1] = "v pořádku"
                    else:
                        row[1] = "více bodů"
                    
                    cursor.updateRow(row)
            
            # 3. Finální polygon řešeného území s atributem "bod"
            final_polygon_name = f"{out_prefix}Resene_uzemi_Polygon_with_Points" if out_prefix else "Resene_uzemi_Polygon_with_Points"
            final_polygon_fc = os.path.join(output_workspace, generate_unique_fc_name(final_polygon_name, root_gdb))
            
            arcpy.AddMessage(f"[process_resene_point_with_polygon] 3. Vytvářím finální polygon: {final_polygon_fc}")
            arcpy.management.CopyFeatures(temp_join, final_polygon_fc)
            
            # Vyhodnocení výsledku pro reporting
            with arcpy.da.SearchCursor(final_polygon_fc, ["bod"]) as cursor:
                for row in cursor:
                    hodnoceni = row[0]
                    break
            
            arcpy.AddMessage(f"[process_resene_point_with_polygon] Analýza dokončena:")
            arcpy.AddMessage(f"  - Hodnocení bodu: {hodnoceni}")
            arcpy.AddMessage(f"  - Finální polygon: {os.path.basename(final_polygon_fc)}")
            
            # Vyčištění dočasných dat
            arcpy.Delete_management(temp_join)
            
            return final_polygon_fc
            
        except Exception as e:
            arcpy.AddError(f"[process_resene_point_with_polygon] Chyba při zpracování: {e}")
            return None

    def process_resene_point_with_line(self, snapped_line_fc, resene_point_fc, output_workspace, out_prefix):
        """
        Zpracuje bod Resene_uzemi s přichycenou linií - vytvoří polygon z linie, spatial join, vrátí polygon s atributem "bod".
        """
        arcpy.AddMessage("[process_resene_point_with_line] Začínám zpracování bodu Resene_uzemi s linií.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # 1. Vytvoření polygonu z snapped linie pomocí Feature to Polygon
            temp_polygon = "in_memory\\temp_resene_polygon"
            arcpy.AddMessage(f"[process_resene_point_with_line] 1. Vytvářím polygon z snapped linie pomocí Feature to Polygon")
            arcpy.management.FeatureToPolygon(
                in_features=snapped_line_fc,
                out_feature_class=temp_polygon,
                cluster_tolerance="",
                attributes="ATTRIBUTES"
            )
            
            # 2. Spatial Join bodu k polygonu
            temp_join = "in_memory\\temp_resene_join"
            arcpy.AddMessage(f"[process_resene_point_with_line] 2. Spatial join bodu k polygonu")
            arcpy.analysis.SpatialJoin(
                target_features=temp_polygon,
                join_features=resene_point_fc,
                out_feature_class=temp_join,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="CONTAINS"
            )
            
            # 3. Přidání pole "bod" s hodnocením
            arcpy.management.AddField(temp_join, "bod", "TEXT", field_length=20)
            
            arcpy.AddMessage("[process_resene_point_with_line] 3. Nastavuji hodnocení bodu")
            with arcpy.da.UpdateCursor(temp_join, ["Join_Count", "bod"]) as cursor:
                for row in cursor:
                    join_count = row[0] if row[0] is not None else 0
                    
                    if join_count == 0:
                        row[1] = "bez bodu"
                    elif join_count == 1:
                        row[1] = "v pořádku"
                    else:
                        row[1] = "více bodů"
                    
                    cursor.updateRow(row)
            
            # 4. Finální polygon řešeného území s atributem "bod"
            final_polygon_name = f"{out_prefix}Resene_uzemi_Polygon_with_Points" if out_prefix else "Resene_uzemi_Polygon_with_Points"
            final_polygon_fc = os.path.join(output_workspace, generate_unique_fc_name(final_polygon_name, root_gdb))
            
            arcpy.AddMessage(f"[process_resene_point_with_line] 4. Vytvářím finální polygon: {final_polygon_fc}")
            arcpy.management.CopyFeatures(temp_join, final_polygon_fc)
            
            # 5. Vyčištění dočasných dat (včetně snapped linie)
            arcpy.Delete_management(temp_polygon)
            arcpy.Delete_management(temp_join)
            arcpy.Delete_management(snapped_line_fc)  # Smazání dočasné snapped linie
            
            # 6. Statistiky
            bod_value = None
            with arcpy.da.SearchCursor(final_polygon_fc, ["bod"]) as cursor:
                for row in cursor:
                    bod_value = row[0]
                    break
            
            arcpy.AddMessage(f"[process_resene_point_with_line] Analýza dokončena:")
            arcpy.AddMessage(f"  - Hodnocení bodu: {bod_value}")
            arcpy.AddMessage(f"  - Finální polygon: {os.path.basename(final_polygon_fc)}")
            
            return final_polygon_fc  # Vrácení polygonu s atributem "bod"
            
        except Exception as e:
            arcpy.AddError(f"[process_resene_point_with_line] Chyba při zpracování: {e}")
            return None

    def add_within_analysis(self, target_polygon_fc, main_polygon_fc, output_workspace, out_prefix):
        """
        Přidá analýzu "within" - kontroluje, zda polygony leží uvnitř hlavního polygonu řešeného území.
        """
        arcpy.AddMessage("[add_within_analysis] Začínám analýzu 'within' vůči hlavnímu polygonu řešeného území.")
        
        try:
            # Debug informace o vstupních vrstvách
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Target vrstva: {target_polygon_fc}")
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Main vrstva: {main_polygon_fc}")
            
            # Debug informace
            target_count = arcpy.GetCount_management(target_polygon_fc).getOutput(0)
            main_count = arcpy.GetCount_management(main_polygon_fc).getOutput(0)
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Target polygonů: {target_count}, Main polygonů: {main_count}")
            
            # Kontrola spatial reference
            target_desc = arcpy.Describe(target_polygon_fc)
            main_desc = arcpy.Describe(main_polygon_fc)
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Target SR: {target_desc.spatialReference.name}")
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Main SR: {main_desc.spatialReference.name}")
            
            # Debug informace o hlavním polygonu
            with arcpy.da.SearchCursor(main_polygon_fc, ["SHAPE@"]) as cursor:
                for row in cursor:
                    main_shape = row[0]
                    if main_shape:
                        extent = main_shape.extent
                        area = main_shape.area
                        arcpy.AddMessage(f"[add_within_analysis] DEBUG: Main polygon - Area={area:.2f}, Extent: {extent.XMin:.2f},{extent.YMin:.2f} to {extent.XMax:.2f},{extent.YMax:.2f}")
                    break
            
            # 1. Přidání pole "pozice_resene_uzemi"
            arcpy.management.AddField(target_polygon_fc, "pozice_resene_uzemi", "TEXT", field_length=25)
            
            # 2. Select by Location (stejně jako manuální test v ArcGIS Pro)
            arcpy.AddMessage(f"[add_within_analysis] 1. Select by Location (WITHIN) stejně jako manuální test")
            
            # Vytvoříme feature layer pro select by location
            temp_layer = "temp_target_layer"
            arcpy.management.MakeFeatureLayer(target_polygon_fc, temp_layer)
            
            # Select by Location - vybereme ty co jsou WITHIN
            arcpy.management.SelectLayerByLocation(
                in_layer=temp_layer,
                overlap_type="WITHIN", 
                select_features=main_polygon_fc,
                selection_type="NEW_SELECTION"
            )
            
            # Debug - kolik se vybere
            selected_count = arcpy.GetCount_management(temp_layer).getOutput(0)
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Select by Location vybralo {selected_count} polygonů jako WITHIN")
            
            # 3. Označíme vybrané jako "uvnitř řešeného území"
            with arcpy.da.UpdateCursor(temp_layer, ["OBJECTID", "pozice_resene_uzemi"]) as cursor:
                inside_count = 0
                for row in cursor:
                    row[1] = "uvnitř řešeného území"
                    cursor.updateRow(row)
                    inside_count += 1
            
            # 4. Vymažeme selection a označíme zbytek jako "mimo řešené území"
            arcpy.management.SelectLayerByAttribute(temp_layer, "CLEAR_SELECTION")
            
            outside_count = 0
            with arcpy.da.UpdateCursor(target_polygon_fc, ["OBJECTID", "pozice_resene_uzemi"]) as cursor:
                for row in cursor:
                    if row[1] is None or row[1] == "":  # Neoznačené = mimo
                        row[1] = "mimo řešené území"
                        cursor.updateRow(row)
                        outside_count += 1
            
            total_count = inside_count + outside_count
            
            arcpy.AddMessage(f"[add_within_analysis] DEBUG: Uvnitř: {inside_count}, Mimo: {outside_count}, Celkem: {total_count}")
            
            # 5. Vyčištění dočasných dat
            arcpy.Delete_management(temp_layer)
            
            arcpy.AddMessage(f"[add_within_analysis] Analýza 'within' dokončena - přidáno pole 'pozice_resene_uzemi'")
            
        except Exception as e:
            arcpy.AddError(f"[add_within_analysis] Chyba při analýze within: {e}")

    def split_analysis_by_layer(self, analysis_fc, output_workspace, out_prefix):
        """
        Splituje vrstvu Resene_uzemi_with_Points podle pole Layer.
        Vytvoří samostatnou vrstvu pro každou unikátní hodnotu v poli Layer.
        Vrátí seznam vytvořených vrstev.
        """
        arcpy.AddMessage("[split_analysis_by_layer] Začínám split vrstvy podle pole Layer.")
        
        split_results = []
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # Načtení unikátních hodnot z pole Layer
            layer_values = set()
            with arcpy.da.SearchCursor(analysis_fc, ["Layer"]) as cursor:
                for row in cursor:
                    if row[0]:
                        layer_values.add(row[0])
            
            arcpy.AddMessage(f"[split_analysis_by_layer] Nalezeny hodnoty v poli 'Layer': {sorted(layer_values)}")
            
            # Vytvoření samostatné vrstvy pro každou Layer hodnotu
            for layer_value in sorted(layer_values):
                try:
                    # Sanitizace Layer hodnoty pro název FC - BEZ prefixu (prefix je již v out_prefix)
                    sanitized_layer = sanitize_fc_name(layer_value)
                    
                    # Vytvoření jména vrstvy z Layer hodnoty - pokud je sanitizované jméno s prefixem Z, odebrat ho
                    if sanitized_layer.startswith("Z"):
                        sanitized_layer = sanitized_layer[1:]  # Odstranit prefix Z
                    
                    # Vytvoření jména vrstvy z Layer hodnoty
                    split_fc_name = f"{out_prefix}{sanitized_layer}" if out_prefix else sanitized_layer
                    split_fc_name = generate_unique_fc_name(split_fc_name, root_gdb)
                    
                    # Select a kopírování
                    final_fc = os.path.join(output_workspace, split_fc_name)
                    
                    # Where clause s správnými quotes
                    field_delimited = arcpy.AddFieldDelimiters(analysis_fc, "Layer")
                    where_clause = f"{field_delimited} = '{layer_value}'"
                    
                    arcpy.AddMessage(f"[split_analysis_by_layer] Vytvářím vrstvu pro Layer='{layer_value}': {split_fc_name}")
                    arcpy.AddMessage(f"[split_analysis_by_layer] DEBUG: Where clause: {where_clause}")
                    
                    arcpy.analysis.Select(
                        in_features=analysis_fc,
                        out_feature_class=final_fc,
                        where_clause=where_clause
                    )
                    
                    count = arcpy.GetCount_management(final_fc).getOutput(0)
                    
                    # Filtrovat atributy - ponechat pouze požadované
                    self.keep_only_required_fields(final_fc)
                    
                    split_results.append(final_fc)
                    arcpy.AddMessage(f"[split_analysis_by_layer] Vytvořena vrstva: {split_fc_name} ({count} prvků)")
                    
                except Exception as e:
                    arcpy.AddWarning(f"[split_analysis_by_layer] Chyba při vytváření vrstvy pro Layer='{layer_value}': {e}")
            
            arcpy.AddMessage(f"[split_analysis_by_layer] Split dokončen - vytvořeno {len(split_results)} vrstev")
            
        except Exception as e:
            arcpy.AddError(f"[split_analysis_by_layer] Chyba při splitu: {e}")
        
        return split_results

    def keep_only_required_fields(self, feature_class):
        """
        Ponechá pouze požadované atributy ve feature class.
        Všechny ostatní atributy budou odstraněny.
        """
        arcpy.AddMessage(f"[keep_only_required_fields] Filtruji atributy v: {os.path.basename(feature_class)}")
        
        # Seznam požadovaných atributů
        required_fields = [
            "OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO", "DOK_NAZEV",
            "RIMSA_MIN", "RIMSA_MAX", "VYSKA_VB", "VYSKA_VB_I", "PODTYP",
            "NP_MIN", "NP_MAX", "NUP_MAX", "VYSKA_MAX", "VYSKA_VB_D",
            "bod", "pozice_resene_uzemi",
            # Výškové atributy s prefixem VR_
            "VR_OZNACENI", "VR_NAZEV_BLOK", "VR_DRUH_UP", "VR_DRUH_INFO", "VR_DOK_NAZEV",
            "VR_RIMSA_MIN", "VR_RIMSA_MAX", "VR_VYSKA_VB", "VR_VYSKA_VB_I", "VR_PODTYP",
            "VR_NP_MIN", "VR_NP_MAX", "VR_NUP_MAX", "VR_VYSKA_MAX", "VR_VYSKA_VB_D"
        ]
        
        try:
            # Získání seznamu všech polí
            all_fields = arcpy.ListFields(feature_class)
            
            # Systémová pole, která nesmíme smazat
            system_fields = ["OBJECTID", "FID", "Shape", "Shape_Length", "Shape_Area", "SHAPE"]
            
            # Pole ke smazání
            fields_to_delete = []
            
            for field in all_fields:
                # Přeskočit systémová pole a požadované pole
                if field.name.upper() in [f.upper() for f in system_fields]:
                    continue
                if field.name in required_fields:
                    continue
                
                # Pole není v požadovaných - smazat
                if not field.required:  # Pouze pokud není povinné
                    fields_to_delete.append(field.name)
            
            # Smazání nepotřebných polí
            if fields_to_delete:
                arcpy.AddMessage(f"[keep_only_required_fields] Mažu {len(fields_to_delete)} nepotřebných polí")
                arcpy.management.DeleteField(feature_class, fields_to_delete)
            else:
                arcpy.AddMessage(f"[keep_only_required_fields] Žádná pole ke smazání")
                
        except Exception as e:
            arcpy.AddWarning(f"[keep_only_required_fields] Chyba při filtrování polí: {e}")

    def create_error_polygon_bod(self, analysis_fc, output_workspace, out_prefix):
        """
        Vytvoří sloučený polygon ze všech polygonů, kde pole 'bod' != "v pořádku".
        Vrátí cestu k vytvořenému feature class nebo None.
        """
        arcpy.AddMessage("[create_error_polygon_bod] Vytvářím chybový polygon pro špatné body.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # Kontrola, zda existuje pole 'bod'
            field_list = [f.name for f in arcpy.ListFields(analysis_fc)]
            if "bod" not in field_list:
                arcpy.AddWarning("[create_error_polygon_bod] Pole 'bod' neexistuje - přeskakuji")
                return None
            
            # Vytvoření dočasné vrstvy s chybnými polygony
            temp_error = "in_memory\\temp_error_bod"
            
            # Where clause pro výběr polygonů s chybou
            where_clause = "bod <> 'v pořádku'"
            
            arcpy.AddMessage(f"[create_error_polygon_bod] Vybírám polygony s podmínkou: {where_clause}")
            arcpy.analysis.Select(
                in_features=analysis_fc,
                out_feature_class=temp_error,
                where_clause=where_clause
            )
            
            # Kontrola počtu vybraných prvků
            error_count = int(arcpy.GetCount_management(temp_error).getOutput(0))
            
            if error_count == 0:
                arcpy.AddMessage("[create_error_polygon_bod] Žádné polygony s chybou bodu - přeskakuji")
                arcpy.Delete_management(temp_error)
                return None
            
            arcpy.AddMessage(f"[create_error_polygon_bod] Nalezeno {error_count} polygonů s chybou bodu")
            
            # Dissolve (sloučení) všech chybových polygonů do jednoho
            error_fc_name = f"{out_prefix}chyba_bod" if out_prefix else "chyba_bod"
            error_fc = os.path.join(output_workspace, generate_unique_fc_name(error_fc_name, root_gdb))
            
            arcpy.AddMessage(f"[create_error_polygon_bod] Provádím dissolve do: {error_fc_name}")
            arcpy.management.Dissolve(
                in_features=temp_error,
                out_feature_class=error_fc,
                dissolve_field=[],  # Sloučit vše do jednoho polygonu
                multi_part="MULTI_PART"
            )
            
            # Vyčištění dočasných dat
            arcpy.Delete_management(temp_error)
            
            dissolved_count = int(arcpy.GetCount_management(error_fc).getOutput(0))
            arcpy.AddMessage(f"[create_error_polygon_bod] Vytvořen chybový polygon: {os.path.basename(error_fc)} ({dissolved_count} částí)")
            
            return error_fc
            
        except Exception as e:
            arcpy.AddError(f"[create_error_polygon_bod] Chyba při vytváření chybového polygonu: {e}")
            return None

    def create_error_polygon_resene_uzemi(self, analysis_fc, output_workspace, out_prefix):
        """
        Vytvoří sloučený polygon ze všech polygonů, kde 'pozice_resene_uzemi' = "mimo řešené území".
        Vrátí cestu k vytvořenému feature class nebo None.
        """
        arcpy.AddMessage("[create_error_polygon_resene_uzemi] Vytvářím chybový polygon pro polygony mimo řešené území.")
        
        try:
            # Získání kořenové geodatabáze pro kontrolu jedinečnosti názvů
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
            
            # Kontrola, zda existuje pole 'pozice_resene_uzemi'
            field_list = [f.name for f in arcpy.ListFields(analysis_fc)]
            if "pozice_resene_uzemi" not in field_list:
                arcpy.AddWarning("[create_error_polygon_resene_uzemi] Pole 'pozice_resene_uzemi' neexistuje - přeskakuji")
                return None
            
            # Vytvoření dočasné vrstvy s chybnými polygony
            temp_error = "in_memory\\temp_error_resene_uzemi"
            
            # Where clause pro výběr polygonů mimo území
            where_clause = "pozice_resene_uzemi = 'mimo řešené území'"
            
            arcpy.AddMessage(f"[create_error_polygon_resene_uzemi] Vybírám polygony s podmínkou: {where_clause}")
            arcpy.analysis.Select(
                in_features=analysis_fc,
                out_feature_class=temp_error,
                where_clause=where_clause
            )
            
            # Kontrola počtu vybraných prvků
            error_count = int(arcpy.GetCount_management(temp_error).getOutput(0))
            
            if error_count == 0:
                arcpy.AddMessage("[create_error_polygon_resene_uzemi] Žádné polygony mimo řešené území - přeskakuji")
                arcpy.Delete_management(temp_error)
                return None
            
            arcpy.AddMessage(f"[create_error_polygon_resene_uzemi] Nalezeno {error_count} polygonů mimo řešené území")
            
            # Dissolve (sloučení) všech chybových polygonů do jednoho
            error_fc_name = f"{out_prefix}chyba_resene_uzemi" if out_prefix else "chyba_resene_uzemi"
            error_fc = os.path.join(output_workspace, generate_unique_fc_name(error_fc_name, root_gdb))
            
            arcpy.AddMessage(f"[create_error_polygon_resene_uzemi] Provádím dissolve do: {error_fc_name}")
            arcpy.management.Dissolve(
                in_features=temp_error,
                out_feature_class=error_fc,
                dissolve_field=[],  # Sloučit vše do jednoho polygonu
                multi_part="MULTI_PART"
            )
            
            # Vyčištění dočasných dat
            arcpy.Delete_management(temp_error)
            
            dissolved_count = int(arcpy.GetCount_management(error_fc).getOutput(0))
            arcpy.AddMessage(f"[create_error_polygon_resene_uzemi] Vytvořen chybový polygon: {os.path.basename(error_fc)} ({dissolved_count} částí)")
            
            return error_fc
            
        except Exception as e:
            arcpy.AddError(f"[create_error_polygon_resene_uzemi] Chyba při vytváření chybového polygonu: {e}")
            return None



class Toolbox(object):
    def __init__(self):
        self.label = "CAD Import Tools - Řešená území"
        self.alias = "CAD_ReseneUzemi"
        self.tools = [ExportLayer]


class ExportLayer(object):
    def __init__(self):
        self.label = "Import CAD do GIS (Řešená území)"
        self.alias = "exportCadLayer"
        self.canRunInBackground = False
        self.parameters = [
            parameter("Input CAD Soubor", "input_cad", "DEFile"),
            parameter("CAD Vrstva(y)", "cad_layers", "GPString", parameterType="Optional", multiValue=True),
            parameter("Output Geodatabáze", "output_gdb", "DEWorkspace"),
            parameter("Output Feature Dataset (Optional)", "output_fd", "GPString", parameterType="Optional"),
            parameter("XY Tolerance (m)", "xy_tolerance", "GPDouble", parameterType="Optional", defaultValue=0.01),
            parameter("XY Resolution (m)", "xy_resolution", "GPDouble", parameterType="Optional", defaultValue=0.001),
            parameter("Output Souřadnicový Systém", "output_sr", "GPSpatialReference", parameterType="Optional"),
            parameter("Geographic Transformation (Optional)", "transformation", "GPString", parameterType="Optional"),
            parameter("Prefix jména výstupu (Optional)", "out_prefix", "GPString", parameterType="Optional", defaultValue="Z"),
        ]

    def getParameterInfo(self):
        self.parameters[0].filter.list = ["dwg", "dxf", "dgn"]
        self.parameters[2].filter.list = ["Local Database", "Remote Database"]
        self.parameters[1].enabled = False
        return self.parameters

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and parameters[0].value:
            try:
                cad_file_path = parameters[0].valueAsText
                cfile = CadFile(cad_file_path)
                parameters[1].filter.list = cfile.layer_display_names
                parameters[1].enabled = True
                
                # Automatické předvybrání specifických vrstev
                default_layers = {
                    "101110_PL_Resene_uzemi": ["Polyline"],
                    "200000_PL_Cast_uzemi": ["Polyline", "Point"], 
                    "101111_BL_Resene_uzemi": ["Point"],  # Speciální zpracování pro linii
                    "202110_BL_Cast_uzemi_UP": ["Point"],
                    "203110_BL_Cast_uzemi_SB": ["Point"], 
                    "204110_BL_Cast_uzemi_NB": ["Point"],
                    "205110_BL_Cast_uzemi_XB": ["Point"],
                    "302310_BL_VR_na_plochu": ["Polyline"],  # Výškové kruhy na plochu
                    "302311_PL_VR_na_plochu_rozhrani": ["Polyline"]  # Rozhraní výškových kruhů
                }
                
                # Najít odpovídající vrstvy v CAD souboru
                selected_layers = []
                for display_name in cfile.layer_display_names:
                    # Extrahovat název vrstvy a typ geometrie z display_name
                    if " (" in display_name and display_name.endswith(")"):
                        layer_name = display_name.split(" (")[0]
                        geometry_type = display_name.split(" (")[1].rstrip(")")
                        
                        # Kontrola, zda vrstva odpovídá požadovaným kritériím
                        if layer_name in default_layers:
                            if geometry_type in default_layers[layer_name]:
                                selected_layers.append(display_name)
                
                if selected_layers:
                    parameters[1].values = selected_layers
                    arcpy.AddMessage(f"[updateParameters] Automaticky předvybrané vrstvy: {selected_layers}")
                
                # Automatické nastavení souřadnicového systému z CAD souboru
                if not parameters[6].altered:
                    desc = arcpy.Describe(cad_file_path)
                    if hasattr(desc, "spatialReference") and desc.spatialReference:
                        sr = desc.spatialReference
                        if sr.name != "Unknown":
                            parameters[6].value = sr
            except Exception as e:
                arcpy.AddWarning(f"[updateParameters] Chyba při načítání CAD: {e}")
        
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True
        
        input_cad = parameters[0].valueAsText
        selected_layers_text = parameters[1].valueAsText
        output_gdb = parameters[2].valueAsText
        fd_name = parameters[3].valueAsText
        xy_tolerance = parameters[4].value if parameters[4].value is not None else 0.01
        xy_resolution = parameters[5].value if parameters[5].value is not None else 0.001
        output_sr = parameters[6].value
        transform_method = parameters[7].valueAsText
        out_prefix = parameters[8].valueAsText or ""

        # Nastavení defaultního spatial reference na S-JTSK pokud není specifikován
        if not output_sr:
            output_sr = arcpy.SpatialReference(5514)  # S-JTSK / Krovak East North
            arcpy.AddMessage(f"[execute] Používám defaultní souřadnicový systém: {output_sr.name} (EPSG:5514)")

        # Vytvoření CAD objektu
        cad_file_obj = CadFile(input_cad)

        # Vytvoření Feature Datasetu pokud je specifikován
        if fd_name:
            fd_path = os.path.join(output_gdb, fd_name)
            if not arcpy.Exists(fd_path):
                arcpy.AddMessage(f"[execute] Tvořím Feature Dataset '{fd_name}' v: {output_gdb}")
                arcpy.AddMessage(f"[execute] XY Tolerance: {xy_tolerance} m, XY Resolution: {xy_resolution} m")
                try:
                    # Nastavení prostředí před vytvořením Feature Datasetu
                    original_xy_tolerance = arcpy.env.XYTolerance
                    original_xy_resolution = arcpy.env.XYResolution
                    
                    arcpy.env.XYTolerance = f"{xy_tolerance} Meters"
                    arcpy.env.XYResolution = f"{xy_resolution} Meters"
                    
                    # Vždy vytvoříme s definovaným spatial reference (buď uživatelem nebo S-JTSK)
                    arcpy.CreateFeatureDataset_management(
                        out_dataset_path=output_gdb, 
                        out_name=fd_name, 
                        spatial_reference=output_sr
                    )
                    
                    # Obnovení původních hodnot prostředí
                    if original_xy_tolerance:
                        arcpy.env.XYTolerance = original_xy_tolerance
                    if original_xy_resolution:
                        arcpy.env.XYResolution = original_xy_resolution
                        
                except Exception as e:
                    arcpy.AddWarning(f"[execute] Nepodařilo se vytvořit FD '{fd_name}': {e}")
                    fd_path = output_gdb
            final_workspace = fd_path
        else:
            final_workspace = output_gdb

        # Vytvoření CAD objektu
        cad_file_obj = CadFile(input_cad)

        # Zpracování vybraných vrstev
        if selected_layers_text:
            selected_layer_list = [x.strip().strip("'").strip('"') for x in selected_layers_text.split(";")]
            arcpy.AddMessage(f"[execute] Exportuji vybrané vrstvy: {selected_layer_list}")
        else:
            selected_layer_list = []

        # Export CAD vrstev
        exported_layers = cad_file_obj.export_layers(
            selected_display_names=selected_layer_list,
            output_workspace=final_workspace,
            spatial_ref=output_sr,
            transform_method=transform_method,
            out_prefix=out_prefix
        )

        if exported_layers:
            arcpy.AddMessage(f"[execute] Úspěšně exportováno {len(exported_layers)} vrstev:")
            for layer in exported_layers:
                arcpy.AddMessage(f"  - {layer}")
        else:
            arcpy.AddWarning("[execute] Žádné vrstvy nebyly exportovány.")
