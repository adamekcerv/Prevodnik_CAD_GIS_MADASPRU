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

    if not arcpy.Exists(gdb_path):
        return fc_names

    # Pokud je gdb_path FeatureDataset, musíme získat parent GDB, abychom zkontrolovali unikátnost v celé GDB
    # Jinak stačí gdb_path
    search_root = gdb_path
    try:
        desc = arcpy.Describe(gdb_path)
        if desc.datatype == "FeatureDataset":
            search_root = os.path.dirname(gdb_path)
    except:
        pass # Pokud nejde describe, necháme původní

    try:
        # Použijeme walk na celou GDB
        walk = arcpy.da.Walk(search_root, datatype="FeatureClass")
        for dirpath, dirnames, filenames in walk:
            for fc in filenames:
                fc_names.add(fc)
    except Exception as e:
        arcpy.AddWarning(f"Chyba při kontrole unikátnosti názvů: {e}")
            
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
    Vygeneruje unikátní název feature class v rámci celé geodatabáze.
    Pokud již jméno existuje kdekoli v GDB, přidá se přípona _1, _2, atd.
    """
    # Sanitizace základního názvu
    base = sanitize_fc_name(base)
    
    # workspace může být Feature Dataset nebo GDB. 
    # get_all_fc_names si s tím poradí a vrátí jména z celé GDB.
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
        
        # Společné atributy pro výškové regulace
        VYSKOVA_REGULACE_ATTRS = [
            "VYSKA_VB", "VYSKA_VB_I", "NP_MIN", "NP_MAX", "NPU_MAX", 
            "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX"
        ]
        
        # Definice modelu pro přejmenování
        self.LAYER_DEFINITIONS_REF = {
            "Z_1011_ReseneUzemi": {
                "TARGET_NAME": "1011_ReseneUzemi_p"
            },
            "Z_2011_UlicniCara": {
                "TARGET_NAME": "2011_UlicniCara_l"
            },
            "Z_2021_UlicniProstranstvi": {
                "TARGET_NAME": "2021_UlicniProstranstvi_p"
            },
            "Z_2031_StavebniBlok": {
                "TARGET_NAME": "2031_StavebniBlok_p"
            },
            "Z_2041_NestavebniBlok": {
                "TARGET_NAME": "2041_NestavebniBlok_p"
            },
            "Z_2051_JinaCastUzemi": {
                "TARGET_NAME": "2051_JinaCastUzemi_p"
            },
            "Z_3011_StavebniCara": {
                "TARGET_NAME": "3011_StavebniCara_l"
            },
            "Z_3021_VyskovaRegulaceNaBod": {
                "TARGET_NAME": "3021_VyskovaRegulaceNaBod_b"
            },
             "Z_3022_VyskovaRegulaceNaLinii": {
                "TARGET_NAME": "3022_VyskovaRegulaceNaLinii_l"
            },
            "Z_3023_VyskovaRegulaceNaPlochu": {
                "TARGET_NAME": "3023_VyskovaRegulaceNaPlochu_p"
            },
            "chyba_bod": {
                "TARGET_NAME": "chyba_bod"
            },
            "chyba_resene_uzemi": {
                "TARGET_NAME": "chyba_resene_uzemi"
            }
        }

    def get_layers(self):
        """
        Načte všechny vrstvy z CAD souboru.
        """
        # Uložení původního workspace
        original_workspace = arcpy.env.workspace
        
        try:
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
        finally:
            # Obnovení původního workspace
            arcpy.env.workspace = original_workspace

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
                    
                    # Smazat původní polygonová vrstva (již máme rozdělené) - ZDE OPRAVA: Původní kód mazal ZResene_uzemi_PL, ale v logu vidíme, že Z200000... zůstává
                    try:
                        if polygon_fc in exported_layers:
                            # polygon_fc je ZResene_uzemi_PL - to chceme smazat, protože máme splitnuté části
                            exported_layers.remove(polygon_fc)
                            arcpy.Delete_management(polygon_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána původní polygonová vrstva: {os.path.basename(polygon_fc)}")

                        # Smazat Z200000_PL_Cast_uzemi_LN - pomocná linie pro tvorbu polygonů
                        # Musíme ji najít v exported_layers, protože má dynamický název (suffix _LN_20 atd.)
                        lines_to_remove = []
                        for layer in exported_layers:
                            if "200000_PL_Cast_uzemi" in layer:
                                lines_to_remove.append(layer)
                        
                        for layer in lines_to_remove:
                            exported_layers.remove(layer)
                            arcpy.Delete_management(layer)
                            arcpy.AddMessage(f"[export_layers] Smazána pomocná linie: {os.path.basename(layer)}")
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
                        # Pokud proběhl split, POUZE tyto vrstvy jsou finální výsledek (kromě chyb)
                        # Odstraníme předchozí "hlavní" polygony ze seznamu exportovaných, pokud tam jsou
                        if updated_main_polygon_fc and updated_main_polygon_fc in exported_layers:
                            exported_layers.remove(updated_main_polygon_fc)
                        if main_polygon_fc and main_polygon_fc in exported_layers:
                            exported_layers.remove(main_polygon_fc)
                            
                        exported_layers.extend(split_results)
                        
                        # SAMOSTATNÝ SPATIAL JOIN VÝŠKOVÝCH BODŮ - NOVÁ LOGIKA
                        if vyska_centroids_fc:
                            try:
                                vyska_polygons_list = []
                                arcpy.AddMessage("[export_layers] Vytvářím samostatné polygony výškové regulace na plochu...")
                                for split_fc in split_results:
                                    # Vytvoří novou vrstvu (fragment), pokud se v polygonu nachází výškový bod
                                    # Fragmenty se pojmenují dočasně, pak se sloučí
                                    vyska_fragment = self.create_vyska_polygon_layer(split_fc, vyska_centroids_fc, output_workspace, out_prefix)
                                    if vyska_fragment:
                                        vyska_polygons_list.append(vyska_fragment)
                                
                                # Sloučení všech fragmentů do jedné vrstvy Z_3023_VyskovaRegulaceNaPlochu_p
                                if vyska_polygons_list:
                                    # out_prefix již obsahuje "_" na konci (zpracováno v execute)
                                    # Takže pokud je prefix "Z_", výsledné jméno bude "Z_3023_..." (správně)
                                    final_vyska_name = f"{out_prefix}3023_VyskovaRegulaceNaPlochu_p"
                                    # Kontrola, zda jméno už existuje (teoreticky nemělo být vytvořeno v split_results, protože tam jsou jiné Layery)
                                    final_vyska_fc = os.path.join(output_workspace, generate_unique_fc_name(final_vyska_name, output_workspace))
                                    
                                    arcpy.AddMessage(f"[export_layers] Slučuji {len(vyska_polygons_list)} fragmentů do finální vrstvy: {os.path.basename(final_vyska_fc)}")
                                    arcpy.management.Merge(vyska_polygons_list, final_vyska_fc)
                                    
                                    # Finalizace atributů nové vrstvy
                                    self.finalize_layer_attributes(final_vyska_fc, "Z_3023_VyskovaRegulaceNaPlochu_p")
                                    exported_layers.append(final_vyska_fc)
                                    
                                    # Smazání fragmentů
                                    for fragment in vyska_polygons_list:
                                        arcpy.Delete_management(fragment)
                                        
                                arcpy.AddMessage("[export_layers] ✓ Vytváření polygonů výškové regulace dokončeno")
                            except Exception as e:
                                arcpy.AddWarning(f"[export_layers] Chyba při vytváření polygonů výškové regulace: {e}")
                    
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
                            if point_fc in exported_layers:
                                exported_layers.remove(point_fc) # Odstranit ze seznamu výstupů
                            arcpy.Delete_management(point_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána bodová vrstva: {os.path.basename(point_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat bodovou vrstvu {os.path.basename(point_fc)}: {e}")
                    
                    # Smazat výškové centroidy - již se nepoužívají
                    if vyska_centroids_fc:
                        try:
                            # Centroidy nebyly v exported_layers, ale pro jistotu
                            if vyska_centroids_fc in exported_layers:
                                exported_layers.remove(vyska_centroids_fc)
                            arcpy.Delete_management(vyska_centroids_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána bodová vrstva výškových centroidů: {os.path.basename(vyska_centroids_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat výškové centroidy: {e}")
                    
                    # Smazat bod Resene_uzemi - již se nepoužívá
                    if resene_point_fc:
                        try:
                            if resene_point_fc in exported_layers:
                                exported_layers.remove(resene_point_fc)
                            arcpy.Delete_management(resene_point_fc)
                            arcpy.AddMessage(f"[export_layers] Smazán bod Resene_uzemi: {os.path.basename(resene_point_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat bod Resene_uzemi: {e}")
                    
                    # FINÁLNÍ CLEANUP - smazat nepotřebné pomocné vrstvy
                    arcpy.AddMessage("[export_layers] Finální cleanup nepotřebných vrstev...")
                    
                    # Smazat původní výškové kruhy (Z302310_BL_VR_na_plochu_LN)
                    if vyska_circles_fc:
                        try:
                            if vyska_circles_fc in exported_layers:
                                exported_layers.remove(vyska_circles_fc)
                            arcpy.Delete_management(vyska_circles_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána původní vrstva výškových kruhů: {os.path.basename(vyska_circles_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat výškové kruhy: {e}")
                    
                    # Smazat filtrované kruhy (Z302310_VR_circles_LN)
                    try:
                        original_ws = arcpy.env.workspace
                        try:
                            arcpy.env.workspace = output_workspace
                            circles_classes = arcpy.ListFeatureClasses("*VR_circles*")
                            for circles_fc in circles_classes:
                                circles_path = os.path.join(output_workspace, circles_fc)
                                arcpy.Delete_management(circles_path)
                                arcpy.AddMessage(f"[export_layers] Smazána vrstva filtrovaných kruhů: {circles_fc}")
                        finally:
                            arcpy.env.workspace = original_ws
                    except Exception as e:
                        arcpy.AddWarning(f"[export_layers] Nelze smazat filtrované kruhy: {e}")
                    
                    # Smazat ZResene_uzemi_Polygon_with_Points (pokud existuje)
                    if updated_main_polygon_fc:
                        try:
                            # Zde je klíčová oprava - odstranit ze seznamu !
                            if updated_main_polygon_fc in exported_layers:
                                exported_layers.remove(updated_main_polygon_fc)
                            arcpy.Delete_management(updated_main_polygon_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána pomocná vrstva: {os.path.basename(updated_main_polygon_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat pomocnou vrstvu Polygon_with_Points: {e}")
                    
                    # Smazat rozhraní výškových kruhů (Z302311_PL_VR_na_plochu_rozhrani_LN)
                    if vyska_rozhrani_fc:
                        try:
                            if vyska_rozhrani_fc in exported_layers:
                                exported_layers.remove(vyska_rozhrani_fc)
                            arcpy.Delete_management(vyska_rozhrani_fc)
                            arcpy.AddMessage(f"[export_layers] Smazána vrstva rozhraní výškových kruhů: {os.path.basename(vyska_rozhrani_fc)}")
                        except Exception as e:
                            arcpy.AddWarning(f"[export_layers] Nelze smazat rozhraní: {e}")
                    
                    # 7. Finalizace atributů pro ostatní vrstvy (linie, body co nešly do spatial joinu)
                    # Projdeme všechny vrstvy co zbyly v exported_layers a pokud to nejsou ty co jsme už řešili (splitnuté polygony),
                    # tak pro ně taky zavoláme finalize_layer_attributes
                    
                    arcpy.AddMessage("[export_layers] Finalizuji atributy pro ostatní vrstvy...")
                    for layer in exported_layers:
                        # Přeskočit už zpracované (splitnuté polygony to nejsou, ty jsou nové FC, ale v exported_layers mohou být jiné)
                        # Zkusíme finalizovat vše co zbylo - finalize_layer_attributes si poradí (buď najde definici nebo warning)
                        
                        # Ale pozor, nechceme to volat na vrstvy co už byly smazány (ale ty by neměly být v seznamu)
                        if arcpy.Exists(layer):
                           try:
                               basename = os.path.basename(layer)
                               # Pokud to má formát Zxxxxxx_..., tak to zkusíme použít
                               # Hledáme kód 201110 atd.
                               potential_code = None
                               
                               # Varianta 1: Zkratka out_prefix (Z) + kód 6 číslic
                               if out_prefix and basename.startswith(out_prefix) and len(basename) >= len(out_prefix) + 6:
                                   check_code = basename[len(out_prefix):len(out_prefix)+6]
                                   if check_code.isdigit():
                                       potential_code = check_code
                                
                               # Varianta 2: Bez prefixu nebo jiný formát - zkusíme najít první 6číslí
                               if not potential_code:
                                   import re
                                   match = re.search(r"\d{6}", basename)
                                   if match:
                                       potential_code = match.group(0)
                               
                               if potential_code:
                                   # Máme kód, použijeme ho jako "layer_name" pro detekci
                                   self.finalize_layer_attributes(layer, potential_code)
                               else:
                                   # Fallback - pošleme celý název
                                   self.finalize_layer_attributes(layer, basename)
                                   
                           except Exception as e:
                               arcpy.AddWarning(f"[export_layers] Chyba při finalizaci {basename}: {e}")

                    # --- PŘEJMENOVÁNÍ VRSTEV PODLE DATOVÉHO MODELU ---
                    arcpy.AddMessage("[export_layers] Přejmenovávám vrstvy podle datového modelu...")
                    arcpy.env.overwriteOutput = True
                    
                    # Získáme seznam všech vrstev v output_workspace
                    arcpy.env.workspace = output_workspace
                    all_fcs = arcpy.ListFeatureClasses()
                    
                    renamed_count = 0
                    for fc in all_fcs:
                        # Zkusíme zjistit typ vrstvy stejnou logikou jako ve finalize_layer_attributes
                        found_key = None
                        fc_basename = os.path.basename(fc)
                        
                        for key in self.LAYER_DEFINITIONS_REF:
                            key_code = "".join(filter(str.isdigit, key))
                            fc_code = "".join(filter(str.isdigit, fc_basename))
                            if key_code and fc_code and fc_code.startswith(key_code):
                                found_key = key
                                break
                        
                        if not found_key:
                            if "chyba_bod" in fc_basename:
                                found_key = "chyba_bod"
                            elif "chyba_resene_uzemi" in fc_basename:
                                found_key = "chyba_resene_uzemi"
                                
                        if found_key and "TARGET_NAME" in self.LAYER_DEFINITIONS_REF[found_key]:
                            target_name = self.LAYER_DEFINITIONS_REF[found_key]["TARGET_NAME"]
                            # Přidáme prefix, pokud existuje a pokud už v target_name není
                            if out_prefix and not target_name.startswith(out_prefix):
                                base_final_name = f"{out_prefix}{target_name}"
                            else:
                                base_final_name = target_name

                            # Geodatabase název nesmí začínat číslem a musí projít validací jména.
                            if base_final_name and base_final_name[0].isdigit():
                                base_final_name = f"Z_{base_final_name}"
                            base_final_name = arcpy.ValidateTableName(base_final_name, output_workspace)
                                
                            # Přejmenování pouze pokud se název liší
                            if fc_basename != base_final_name:
                                # Zajištění unikátnosti názvu v rámci celé GDB
                                existing_names = get_all_fc_names(output_workspace)
                                # Odstraníme aktuální název, abychom ho nebrali jako kolizi
                                if fc_basename in existing_names:
                                    existing_names.remove(fc_basename)
                                    
                                final_name = base_final_name
                                counter = 1
                                while final_name in existing_names:
                                    final_name = f"{base_final_name}_{counter}"
                                    counter += 1
                                
                                # Ještě jedna kontrola, jestli se náhodou nevygeneroval stejný název (např. pokud už měl správnou příponu)
                                if fc_basename != final_name:
                                    try:
                                        arcpy.management.Rename(fc, final_name)
                                        arcpy.AddMessage(f"  - Přejmenováno: {fc_basename} -> {final_name}")
                                        renamed_count += 1
                                        
                                        # Aktualizace v seznamu exported_layers, pokud tam je
                                        for i, exp_layer in enumerate(exported_layers):
                                            if os.path.basename(exp_layer) == fc_basename:
                                                exported_layers[i] = os.path.join(output_workspace, final_name)
                                                
                                    except Exception as e:
                                        arcpy.AddWarning(f"  - Nelze přejmenovat {fc_basename} na {final_name}: {e}")
                    
                    arcpy.AddMessage(f"[export_layers] ✓ Přejmenováno {renamed_count} vrstev.")

                    # Převod řešeného území 1011 z linie na polygon (pokud je v GDB stále jako Polyline)
                    self.convert_resene_uzemi_line_to_polygon(output_workspace, out_prefix, exported_layers)

                    arcpy.AddMessage("[export_layers] ✓ Finální cleanup dokončen")
                    
            except Exception as e:
                arcpy.AddError(f"[export_layers] Chyba při spatial join analýze: {e}")
        
        return exported_layers

    def convert_resene_uzemi_line_to_polygon(self, output_workspace, out_prefix, exported_layers):
        """
        Převede finální vrstvu 1011 řešeného území z Polyline na Polygon.
        Pokud je vrstva už polygonová nebo neexistuje, krok se přeskočí.
        """
        original_workspace = arcpy.env.workspace
        try:
            target_name = self.LAYER_DEFINITIONS_REF.get("Z_1011_ReseneUzemi", {}).get("TARGET_NAME", "1011_ReseneUzemi_p")
            if out_prefix and not target_name.startswith(out_prefix):
                expected_base_name = f"{out_prefix}{target_name}"
            else:
                expected_base_name = target_name

            if expected_base_name and expected_base_name[0].isdigit():
                expected_base_name = f"Z_{expected_base_name}"
            expected_base_name = arcpy.ValidateTableName(expected_base_name, output_workspace)

            arcpy.env.workspace = output_workspace
            all_fcs = arcpy.ListFeatureClasses() or []
            if not all_fcs:
                return

            # Kandidáti: 1) přesný název 2) názvy se stejným prefixem (např. _1)
            ordered_candidates = []
            ordered_candidates.extend([fc for fc in all_fcs if fc == expected_base_name])
            ordered_candidates.extend([fc for fc in all_fcs if fc not in ordered_candidates and fc.startswith(expected_base_name)])

            # Fallback: cokoliv s kódem 1011 v názvu
            if not ordered_candidates:
                ordered_candidates.extend([fc for fc in all_fcs if "1011" in "".join(filter(str.isdigit, fc))])

            resene_line_fc_name = None
            for fc_name in ordered_candidates:
                try:
                    fc_path = os.path.join(output_workspace, fc_name)
                    shape_type = arcpy.Describe(fc_path).shapeType
                    if shape_type and shape_type.lower() == "polyline":
                        resene_line_fc_name = fc_name
                        break
                except Exception:
                    continue

            if not resene_line_fc_name:
                arcpy.AddMessage("[convert_resene_uzemi_line_to_polygon] Vrstva 1011 není polyline nebo nebyla nalezena - krok přeskočen.")
                return

            line_fc = os.path.join(output_workspace, resene_line_fc_name)
            temp_polygon_name = generate_unique_fc_name(f"{resene_line_fc_name}_poly_temp", output_workspace)
            temp_polygon_fc = os.path.join(output_workspace, temp_polygon_name)

            arcpy.AddMessage(f"[convert_resene_uzemi_line_to_polygon] Převádím {resene_line_fc_name} na polygon.")
            arcpy.management.FeatureToPolygon(
                in_features=line_fc,
                out_feature_class=temp_polygon_fc,
                attributes="ATTRIBUTES"
            )

            polygon_count = int(arcpy.GetCount_management(temp_polygon_fc)[0])
            if polygon_count == 0:
                arcpy.AddWarning("[convert_resene_uzemi_line_to_polygon] FeatureToPolygon nevytvořil žádný polygon. Ponechávám původní linii.")
                arcpy.Delete_management(temp_polygon_fc)
                return

            arcpy.Delete_management(line_fc)
            arcpy.management.Rename(temp_polygon_fc, resene_line_fc_name)
            new_fc_path = os.path.join(output_workspace, resene_line_fc_name)

            # Doplnění finálních atributů po změně geometrie.
            self.finalize_layer_attributes(new_fc_path, "1011")

            for idx, layer in enumerate(exported_layers):
                if os.path.basename(layer) == resene_line_fc_name:
                    exported_layers[idx] = new_fc_path

            arcpy.AddMessage(f"[convert_resene_uzemi_line_to_polygon] ✓ Vrstva {resene_line_fc_name} převedena na polygon ({polygon_count} prvků).")

        except Exception as e:
            arcpy.AddWarning(f"[convert_resene_uzemi_line_to_polygon] Chyba při převodu 1011 na polygon: {e}")
        finally:
            arcpy.env.workspace = original_workspace

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

    def create_vyska_polygon_layer(self, polygon_fc, points_fc, output_workspace, out_prefix):
        """
        Vytvoří novou polygonovou vrstvu, která vznikne průnikem (spatial joinem) 
        vstupních polygonů a bodů výškové regulace.
        Přenese atributy z bodů do výsledných polygonů.
        """
        arcpy.AddMessage(f"[create_vyska_polygon_layer] Analyzuji výškovou regulaci pro: {os.path.basename(polygon_fc)}")
        
        try:
            # Získání kořenové geodatabáze
            desc_ws = arcpy.Describe(output_workspace)
            if desc_ws.datatype == "FeatureDataset":
                root_gdb = os.path.dirname(output_workspace)
            else:
                root_gdb = output_workspace
                
            # Dočasný soubor pro join
            temp_join_fc = "in_memory\\temp_vyska_join"
            
            # Seznam atributů k přenosu (výškové atributy) - dle modelu
            transfer_attrs = [
                "VYSKA_VB", "VYSKA_VB_I", "NP_MIN", "NP_MAX", "NPU_MAX", 
                "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX"
            ]
            
            # Mapování polí pro FieldMappings: zachovat polygon, přidat body
            field_mappings = arcpy.FieldMappings()
            
            # 1. Přidat všechna pole z polygonu
            field_mappings.addTable(polygon_fc)
            
            # 2. Přidat výškové atributy z bodů
            # Musíme najít správná pole ve zdrojové vrstvě (points_fc)
            all_fields = [f.name for f in arcpy.ListFields(points_fc)]
            points_fields_map = {f.name.upper(): f.name for f in arcpy.ListFields(points_fc)}
            arcpy.AddMessage(f"[create_vyska_polygon_layer] Dostupné atributy v bodech: {all_fields}")
            
            found_any = False
            for target_attr in transfer_attrs:
                # Hledáme atribut ve zdroji (case-insensitive, různé varianty názvu)
                # Varianty: NÁZEV, VR_NÁZEV
                possible_keys = [target_attr, f"VR_{target_attr}"]
                if target_attr == "NPU_MAX": # Specifický fix pro překlepy
                    possible_keys.extend(["NUP_MAX", "VR_NUP_MAX"])
                
                # Běžné varianty v CADu
                if target_attr == "NP_MIN":
                    possible_keys.extend(["MIN_NP", "NPMIN", "VR_NPMIN", "NP MIN"])
                elif target_attr == "NP_MAX":
                    possible_keys.extend(["MAX_NP", "NPMAX", "VR_NPMAX", "NP MAX"])
                elif target_attr == "RIMSA_MIN":
                    possible_keys.extend(["MIN_RIMSA", "RIMSAMIN", "VR_RIMSAMIN", "RIMSA", "RIMSA MIN"]) # RIMSA bez suffixu často bývá MIN
                elif target_attr == "RIMSA_MAX":
                    possible_keys.extend(["MAX_RIMSA", "RIMSAMAX", "VR_RIMSAMAX", "RIMSA MAX"])
                elif target_attr == "VYSKA_MAX":
                    possible_keys.extend(["MAX_VYSKA", "VYSKAMAX", "VR_VYSKAMAX", "VYSKA", "VYSKA MAX", "VYSKA_TOTAL", "VYSKA_CELKEM"])
                elif target_attr == "VYSKA_VB":
                     possible_keys.extend(["VYSKAVB", "VR_VYSKAVB", "VYSKA VB"])
                
                src_field_name = None
                for n in possible_keys:
                    if n.upper() in points_fields_map:
                        src_field_name = points_fields_map[n.upper()]
                        break
                
                # Pokud stále nenalezeno, zkusíme najít pole končící na požadovaný název (např. BLK_NP_MIN)
                if not src_field_name:
                    for f_name_upper in points_fields_map:
                        if f_name_upper.endswith(target_attr) or f_name_upper.endswith(f"_{target_attr}"):
                             # Ochrana před konflikty (aby NP_MIN nebylo nalezeno v NPU_MIN)
                             if target_attr == "NP_MIN" and "NPU" in f_name_upper: continue
                             src_field_name = points_fields_map[f_name_upper]
                             arcpy.AddMessage(f"[create_vyska_polygon_layer] Nalezeno pole '{src_field_name}' pro '{target_attr}' pomocí suffixu.")
                             break
                
                # Pokud stále nenalezeno, zkusíme najít pole s mezerami (např. "NP MAX")
                if not src_field_name:
                    target_variations = [target_attr.replace("_", " "), target_attr.replace("_", "")]
                    for var in target_variations:
                         if var.upper() in points_fields_map:
                             src_field_name = points_fields_map[var.upper()]
                             arcpy.AddMessage(f"[create_vyska_polygon_layer] Nalezeno pole '{src_field_name}' pro '{target_attr}' (varianta: {var}).")
                             break

                if src_field_name:
                    # Vytvoření FieldMap pro jeden atribut
                    fm = arcpy.FieldMap()
                    fm.addInputField(points_fc, src_field_name)
                    
                    # Nastavení výstupního pole
                    out_field = fm.outputField
                    out_field.name = target_attr
                    out_field.aliasName = target_attr
                    fm.outputField = out_field
                    
                    # Přidání do mappings
                    # Pozor: pokud pole už existuje z polygonu (např. prázdné), FieldMappings ho sloučí?
                    # Raději zkontrolujeme, jestli už v mappingu není
                    existing_index = field_mappings.findFieldMapIndex(target_attr)
                    if existing_index != -1:
                        # Pokud existuje, nahradíme ho (chceme hodnotu z bodu, ne z polygonu)
                        field_mappings.replaceFieldMap(existing_index, fm)
                        # arcpy.AddMessage(f"[create_vyska_polygon_layer] Nalezeno pole '{src_field_name}' pro '{target_attr}'.")
                    else:
                        field_mappings.addFieldMap(fm)
                        # arcpy.AddMessage(f"[create_vyska_polygon_layer] Nalezeno pole '{src_field_name}' pro '{target_attr}'.")
                    
                    found_any = True
                else:
                     pass # Už nebudeme logovat nenašlezené pole jako warning, aby to uživatele nepletlo
                     # arcpy.AddWarning(f"[create_vyska_polygon_layer] Pole pro '{target_attr}' nenalezeno v bodech.")
            
            # Spatial Join (HAVE_THEIR_CENTER_IN - bod musí být uvnitř polygonu)
            # Join type: KEEP_COMMON = INNER JOIN -> zůstanou jen polygony, které mají bod!
            # Tím dostaneme jen ty "napojené" části
            arcpy.analysis.SpatialJoin(
                target_features=polygon_fc,
                join_features=points_fc,
                out_feature_class=temp_join_fc,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_COMMON",
                match_option="CONTAINS", # Polygon obsahuje bod
                field_mapping=field_mappings
            )
            
            count = int(arcpy.GetCount_management(temp_join_fc).getOutput(0))
            
            if count == 0:
                # Žádný průnik = žádná regulace v této části
                arcpy.Delete_management(temp_join_fc)
                return None
            
            # Pokud něco nalezeno, uložíme to jako dočasný feature class na disk (fragment)
            # Tyto fragmenty se pak sloučí
            base_name = os.path.basename(polygon_fc) + "_VR_fragment"
            out_name = generate_unique_fc_name(base_name, root_gdb)
            out_fc = os.path.join(output_workspace, out_name)
            
            arcpy.management.CopyFeatures(temp_join_fc, out_fc)
            
            arcpy.AddMessage(f"[create_vyska_polygon_layer] Nalezeno {count} polygonů s regulací -> {out_name}")
            
            # Cleanup
            arcpy.Delete_management(temp_join_fc)
            
            return out_fc
            
        except Exception as e:
            arcpy.AddWarning(f"[create_vyska_polygon_layer] Chyba: {e}")
            return None

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
                    
                    # Pokud po odstranění Z začíná podtržítkem, taky odstranit (aby nevzniklo Z__xxx)
                    if sanitized_layer.startswith("_"):
                        sanitized_layer = sanitized_layer[1:]
                    
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
                    
                    # Filtrovat atributy - ponechat pouze požadované a doplnit systémové
                    self.finalize_layer_attributes(final_fc, layer_value)
                    
                    split_results.append(final_fc)
                    arcpy.AddMessage(f"[split_analysis_by_layer] Vytvořena vrstva: {split_fc_name} ({count} prvků)")
                    
                except Exception as e:
                    arcpy.AddWarning(f"[split_analysis_by_layer] Chyba při vytváření vrstvy pro Layer='{layer_value}': {e}")
            
            arcpy.AddMessage(f"[split_analysis_by_layer] Split dokončen - vytvořeno {len(split_results)} vrstev")
            
        except Exception as e:
            arcpy.AddError(f"[split_analysis_by_layer] Chyba při splitu: {e}")
        
        return split_results

    def finalize_layer_attributes(self, feature_class, layer_name):
        """
        Finalizuje atributy vrstvy podle GIS datového modelu.
        1. Definice datových typů a validace.
        2. Konverze hodnot (např. "15 m" -> 15.0).
        3. Ponechání pouze povolených atributů.
        """
        arcpy.AddMessage(f"[finalize_layer_attributes] Finalizuji atributy pro: {os.path.basename(feature_class)}")
        validation_report = []
        
        # --- 1. Definice metadat a schématu ---
        
        # Definice datových typů pro jednotlivé atributy
        # (Název atributu) -> (Typ, Délka, Alias)
        FIELD_SCHEMA = {
            "SKNAZEV": ("TEXT", 50, "SKNAZEV"),
            "OBTYPNAZEV": ("TEXT", 50, "OBTYPNAZEV"),
            "DOK_NAZEV": ("TEXT", 255, "DOK_NAZEV"),
            "ID_LOKAL": ("SHORT", None, "ID_LOKAL"),
            "OZNACENI": ("TEXT", 25, "OZNACENI"),
            "DRUH_UP": ("TEXT", 10, "DRUH_UP"),
            "DRUH_INFO": ("TEXT", 255, "DRUH_INFO"),
            "PODTYP": ("TEXT", 255, "PODTYP"),
            "DRUH_SC": ("TEXT", 10, "DRUH_SC"),
            
            # Výškové atributy
            "VYSKA_VB": ("TEXT", 10, "VYSKA_VB"),
            "VYSKA_VB_I": ("TEXT", 255, "VYSKA_VB_I"),
            "NP_MIN": ("SHORT", None, "NP_MIN"),
            "NP_MAX": ("SHORT", None, "NP_MAX"),
            "NPU_MAX": ("SHORT", None, "NPU_MAX"),
            "RIMSA_MIN": ("FLOAT", None, "RIMSA_MIN"),
            "RIMSA_MAX": ("FLOAT", None, "RIMSA_MAX"),
            "VYSKA_MAX": ("FLOAT", None, "VYSKA_MAX"),
            
            # Chybové
            "bod": ("TEXT", 255, "bod")
        }
        
        # Slovník mapování: Název vrstvy (část) -> (SKNAZEV, OBTYPNAZEV, Seznam povolených atributů)
        # Poznámka: ID_LOKAL je povinné u všech.
        
        # Společné atributy pro výškové regulace
        VYSKOVA_REGULACE_ATTRS = [
            "VYSKA_VB", "VYSKA_VB_I", "NP_MIN", "NP_MAX", "NPU_MAX", 
            "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX"
        ]
        
        # Společné atributy pro popis
        COMMON_ATTRS = ["OZNACENI", "DOK_NAZEV"]

        # Definice modelu
        LAYER_DEFINITIONS = {
            "Z_1011_ReseneUzemi": {
                "SKNAZEV": "metadata dokumentace",
                "OBTYPNAZEV": "řešené území",
                "ATTRS": ["DOK_NAZEV"],
                "TARGET_NAME": "1011_ReseneUzemi_p"
            },
            "Z_2011_UlicniCara": {
                "SKNAZEV": "členění území",
                "OBTYPNAZEV": "uliční čára",
                "ATTRS": ["ID_LOKAL"],
                "TARGET_NAME": "2011_UlicniCara_l"
            },
            "Z_2021_UlicniProstranstvi": {
                "SKNAZEV": "členění území",
                "OBTYPNAZEV": "uliční prostranství",
                "ATTRS": ["DRUH_UP", "DRUH_INFO", "OZNACENI", "ID_LOKAL"],
                "TARGET_NAME": "2021_UlicniProstranstvi_p"
            },
            "Z_2031_StavebniBlok": {
                "SKNAZEV": "členění území",
                "OBTYPNAZEV": "stavební blok",
                "ATTRS": ["OZNACENI", "ID_LOKAL"],
                "TARGET_NAME": "2031_StavebniBlok_p"
            },
            "Z_2041_NestavebniBlok": {
                "SKNAZEV": "členění území",
                "OBTYPNAZEV": "nestavební blok",
                "ATTRS": ["OZNACENI", "ID_LOKAL"],
                "TARGET_NAME": "2041_NestavebniBlok_p"
            },
            "Z_2051_JinaCastUzemi": {
                "SKNAZEV": "členění území",
                "OBTYPNAZEV": "jiná část území",
                "ATTRS": ["PODTYP", "OZNACENI", "ID_LOKAL"],
                "TARGET_NAME": "2051_JinaCastUzemi_p"
            },
            "Z_3011_StavebniCara": {
                "SKNAZEV": "regulace struktury",
                "OBTYPNAZEV": "stavební čára",
                "ATTRS": ["DRUH_SC", "DRUH_INFO", "ID_LOKAL"],
                "TARGET_NAME": "3011_StavebniCara_l"
            },
            "Z_3021_VyskovaRegulaceNaBod": {
                "SKNAZEV": "regulace struktury",
                "OBTYPNAZEV": "výšková regulace na bod",
                "ATTRS": VYSKOVA_REGULACE_ATTRS + ["ID_LOKAL"],
                "TARGET_NAME": "3021_VyskovaRegulaceNaBod_b"
            },
             "Z_3022_VyskovaRegulaceNaLinii": {
                "SKNAZEV": "regulace struktury",
                "OBTYPNAZEV": "výšková regulace na linii",
                "ATTRS": VYSKOVA_REGULACE_ATTRS + ["ID_LOKAL"],
                "TARGET_NAME": "3022_VyskovaRegulaceNaLinii_l"
            },
            "Z_3023_VyskovaRegulaceNaPlochu": {
                "SKNAZEV": "regulace struktury",
                "OBTYPNAZEV": "výšková regulace na plochu",
                "ATTRS": VYSKOVA_REGULACE_ATTRS + ["ID_LOKAL"],
                "TARGET_NAME": "3023_VyskovaRegulaceNaPlochu_p"
            },
            "chyba_bod": {
                "SKNAZEV": "chyba",
                "OBTYPNAZEV": "chyba bodu",
                "ATTRS": ["bod"],
                "TARGET_NAME": "chyba_bod"
            },
            "chyba_resene_uzemi": {
                "SKNAZEV": "chyba",
                "OBTYPNAZEV": "mimo řešené území",
                "ATTRS": [],
                "TARGET_NAME": "chyba_resene_uzemi"
            }
        }
        
        # --- 2. Identifikace typu vrstvy podle názvu ---
        current_def = None
        found_key = None
        
        # Priorita 1: Identifikace podle původního názvu vrstvy (layer_name)
        if layer_name:
            norm_layer = layer_name.replace("_", "").upper()
            for key in LAYER_DEFINITIONS:
                key_code = "".join(filter(str.isdigit, key))
                layer_code = "".join(filter(str.isdigit, layer_name))
                if key_code and layer_code and layer_code.startswith(key_code):
                    found_key = key
                    break
        
        # Priorita 2: Identifikace podle názvu feature class (fc_basename)
        if not found_key:
            fc_basename = os.path.basename(feature_class)
            for key in LAYER_DEFINITIONS:
                key_code = "".join(filter(str.isdigit, key))
                fc_code = "".join(filter(str.isdigit, fc_basename))
                if key_code and fc_code and fc_code.startswith(key_code):
                    found_key = key
                    break
            
            if not found_key:
                if "chyba_bod" in fc_basename:
                    found_key = "chyba_bod"
                elif "chyba_resene_uzemi" in fc_basename:
                    found_key = "chyba_resene_uzemi"
        
        if found_key:
            current_def = LAYER_DEFINITIONS[found_key]
            arcpy.AddMessage(f"[finalize_layer_attributes] Rozpoznán typ: {found_key}")
        else:
            arcpy.AddWarning(f"[finalize_layer_attributes] POZOR: Nerozpoznaný typ vrstvy '{fc_basename}'. Používám obecná metadata.")
            extra_attrs = []
            if "chyba_bod" in fc_basename:
                extra_attrs.append("bod")
            current_def = {
                "SKNAZEV": "nezarazeno",
                "OBTYPNAZEV": "nezarazeno",
                "ATTRS": COMMON_ATTRS + extra_attrs
            }

        # --- 3. Přidání a validace atributů ---
        
        target_attrs = current_def["ATTRS"] + ["SKNAZEV", "OBTYPNAZEV", "ID_LOKAL"]
        existing_fields = {f.name: f for f in arcpy.ListFields(feature_class)}
        
        for attr_name in target_attrs:
            if attr_name not in FIELD_SCHEMA:
                continue
                
            expected_type, expected_length, expected_alias = FIELD_SCHEMA[attr_name]
            
            field_exists = attr_name in existing_fields
            needs_conversion = False
            
            if field_exists:
                current_field = existing_fields[attr_name]
                current_type_generalized = "TEXT"
                if current_field.type in ["Integer", "SmallInteger"]:
                    current_type_generalized = "SHORT"
                elif current_field.type in ["Double", "Single"]:
                    current_type_generalized = "FLOAT"
                elif current_field.type == "String":
                    current_type_generalized = "TEXT"
                
                is_numeric_target = expected_type in ["SHORT", "FLOAT"]
                is_text_current = current_field.type == "String"
                
                # Pokud cíl je číslo a zdroj je text -> konverze
                if is_numeric_target and is_text_current:
                    needs_conversion = True
                    msg = f"Konverze '{attr_name}': TEXT -> {expected_type}"
                    arcpy.AddMessage(f"[finalize_layer_attributes] {msg}")
                    validation_report.append(msg)
                
                # Pokud cíl je FLOAT a zdroj je Integer/SmallInteger -> konverze (vynucení desetinných míst)
                elif expected_type == "FLOAT" and current_field.type in ["Integer", "SmallInteger"]:
                    needs_conversion = True
                    msg = f"Konverze '{attr_name}': {current_field.type} -> {expected_type} (Vynucení Float)"
                    arcpy.AddMessage(f"[finalize_layer_attributes] {msg}")
                    validation_report.append(msg)
                
                # Pokud cíl je SHORT a zdroj je Float/Double nebo Integer (Long) -> konverze (zaokrouhlení nebo zmenšení)
                elif expected_type == "SHORT" and current_field.type in ["Single", "Double", "Integer"]:
                    needs_conversion = True
                    msg = f"Konverze '{attr_name}': {current_field.type} -> {expected_type} (Vynucení Short)"
                    arcpy.AddMessage(f"[finalize_layer_attributes] {msg}")
                    validation_report.append(msg)
                
            if not field_exists:
                # Vytvoříme nové pole
                arcpy.management.AddField(feature_class, attr_name, expected_type, field_length=expected_length, field_alias=expected_alias)
                validation_report.append(f"Vytvořeno nové pole '{attr_name}' ({expected_type})")
                if attr_name == "OZNACENI":
                    self._fill_oznaceni_from_cad(feature_class, existing_fields.keys())
                    
            elif needs_conversion:
                # Konverze: Vytvoříme TEMP field -> update hodnot -> smazat starý -> přejmenovat TEMP
                temp_field = f"{attr_name}_TMP"
                arcpy.management.AddField(feature_class, temp_field, expected_type, field_alias=expected_alias)
                
                errors = []
                with arcpy.da.UpdateCursor(feature_class, ["OID@", attr_name, temp_field]) as cursor:
                    for row in cursor:
                        oid, val = row[0], row[1]
                        new_val = None
                        if val:
                            try:
                                # Strip "m", space, replace comma with dot
                                s_val = str(val).lower().replace("m", "").replace(" ", "").replace(",", ".")
                                if expected_type == "SHORT":
                                    new_val = int(float(s_val))
                                else:
                                    new_val = float(s_val)
                            except:
                                errors.append(f"OID {oid}: '{val}'")
                        
                        row[2] = new_val
                        cursor.updateRow(row)
                
                if errors:
                    arcpy.AddWarning(f"[finalize_layer_attributes] VAROVÁNÍ: Chyby konverze '{attr_name}' ({len(errors)}x). Příklady: {', '.join(errors[:3])}")
                
                try:
                    arcpy.DeleteField_management(feature_class, attr_name)
                    arcpy.management.AlterField(feature_class, temp_field, new_field_name=attr_name, new_field_alias=expected_alias)
                except Exception as e:
                    arcpy.AddWarning(f"Selhalo přejmenování pole {attr_name}: {e}")

        # --- 4. Naplnění konstant ---
        with arcpy.da.UpdateCursor(feature_class, ["SKNAZEV", "OBTYPNAZEV", "ID_LOKAL"]) as cursor:
            for row in cursor:
                if not row[0]: row[0] = current_def["SKNAZEV"]
                if not row[1]: row[1] = current_def["OBTYPNAZEV"]
                if row[2] is None: row[2] = 0
                cursor.updateRow(row)

        # --- 5. Clean up ---
        system_fields = ["OBJECTID", "FID", "Shape", "Shape_Length", "Shape_Area", "SHAPE", "Shape.STArea()", "Shape.STLength()"]
        allowed_set = set(target_attrs)
        existing_fields_final = arcpy.ListFields(feature_class)
        fields_to_delete = []
        for field in existing_fields_final:
            if field.name not in allowed_set and field.name not in system_fields and field.name.upper() not in [s.upper() for s in system_fields]:
                if not field.required:
                    fields_to_delete.append(field.name)
        
        if fields_to_delete:
            arcpy.management.DeleteField(feature_class, fields_to_delete)

        # --- 6. Souhrnný report ---
        if validation_report:
            arcpy.AddMessage(f"[finalize_layer_attributes] --- SOUHRN ÚPRAV ATRIBUTŮ: {os.path.basename(feature_class)} ---")
            for msg in validation_report:
                arcpy.AddMessage(f"  - {msg}")
            arcpy.AddMessage("------------------------------------------------------")

    def _fill_oznaceni_from_cad(self, feature_class, existing_field_names):
        """Pomocná metoda pro naplnění OZNACENI z CAD atributů"""
        source_col = None
        if "RefName" in existing_field_names: source_col = "RefName"
        elif "Text" in existing_field_names: source_col = "Text"
        elif "NAZEV_BLOK" in existing_field_names: source_col = "NAZEV_BLOK"
        
        if source_col:
            try:
                arcpy.management.CalculateField(feature_class, "OZNACENI", f"!{source_col}!", "PYTHON3")
            except:
                pass

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
            # Na žádost uživatele bez prefixu ("stačí chyba")
            error_fc_name = "chyba_bod"
            error_fc = os.path.join(output_workspace, generate_unique_fc_name(error_fc_name, root_gdb))
            
            arcpy.AddMessage(f"[create_error_polygon_bod] Provádím dissolve do: {error_fc_name}")
            arcpy.management.Dissolve(
                in_features=temp_error,
                out_feature_class=error_fc,
                dissolve_field="bod",  # Sloučit podle typu chyby
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
            error_fc_name = "chyba_resene_uzemi"
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
        
        # Output GDB filter
        self.parameters[2].filter.list = ["Local Database"]
        
        # Nastavení výchozí hodnoty - aktuální projekt GDB nebo C:\GIS_Data\Output.gdb
        try:
            # Zkus použít Default.gdb z aktuálního projektu
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            self.parameters[2].value = aprx.defaultGeodatabase
        except:
            # Fallback - pokud není projekt nebo selže
            try:
                default_path = r"C:\GIS_Data\Output.gdb"
                if arcpy.Exists(default_path):
                    self.parameters[2].value = default_path
            except:
                pass

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
                    "201110_PL_Ulicni_cara": ["Polyline"], # Uliční čára
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

        # Ensure out_prefix ends with "_" if it is not empty
        if out_prefix and not out_prefix.endswith("_"):
            out_prefix += "_"

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
