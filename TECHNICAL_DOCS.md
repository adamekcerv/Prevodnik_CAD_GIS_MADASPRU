# Technická dokumentace - CAD to GIS Toolbox

## Architektura

### Struktura kódu

```
Prevodnik_CAD_GIS_Madaspru.pyt
├── Pomocné funkce
│   ├── sanitize_fc_name() - normalizace názvů feature class
│   ├── generate_unique_fc_name() - generování unikátních názvů
│   ├── parameter() - definice parametrů toolboxu
│   └── get_all_fc_names() - získání existujících FC názvů
├── Třídy
│   ├── CadLayer - reprezentace jednotlivé CAD vrstvy
│   ├── CadFile - reprezentace CAD souboru
│   ├── ExportLayer - hlavní třída toolboxu
│   └── Toolbox - registrace toolboxu
└── Konstanty
    └── GEOMETRY_SUFFIX - přípony dle typu geometrie
```

### Datový tok

```
CAD soubor
  ↓
CadFile.get_layers() - načte všechny dostupné vrstvy
  ↓
export_layers() - kategorizuje vrstvy a orchestruje zpracování
  ├─→ process_polylines_to_polygon() - převod polyline na polygony
  ├─→ perform_spatial_join_analysis() - spatial join bodů k polygonům
  ├─→ split_analysis_by_layer() - rozdělení vrstev dle atributu
  └─→ extract_problem_polygons() - identifikace problematických prvků
  ↓
Exportované vrstvy do geodatabáze
```

## Klíčové metody a operace

### sanitize_fc_name()
Normalizuje názvy feature class podle pravidel ArcGIS geodatabáze.

Pravidla:
- Nahrazuje zvláštní znaky (-, /, \, atd.) podtržítkem
- Pokud název začíná číslem, přidá prefix "Z"
- Výsledek obsahuje jen alfanumerické znaky a podtržítko

Příklady transformace:
```
202110_BL_Cast_uzemi_UP → Z202110_BL_Cast_uzemi_UP
200000/Cast_uzemi → Z200000_Cast_uzemi
```

### CadLayer.export()
Exportuje jednu CAD vrstvu do geodatabáze.

Parametry:
- output_workspace: cílový workspace (GDB nebo FD)
- spatial_ref: výstupní souřadnicový systém
- transform_method: transformační metoda pro reprojekci
- out_prefix: prefix pro název vrstvy

Proces:
1. Validace názvu (SQL-safe)
2. Kontrola jedinečnosti v geodatabázi
3. Filtrování vrstvy dle Layer atributu v CAD
4. Export pomocí FeatureClassToFeatureClass
5. Definice a reprojekce souřadnicového systému

Výstup: cesta k exportované FC nebo None při chybě

### CadFile.export_layers()
Orchestrace exportu všech vybraných vrstev s kategorizací.

Kategorie vrstev:
- **special_polyline**: 101110_PL_Resene_uzemi, 200000_PL_Cast_uzemi
- **special_point**: 202110_BL_Cast_uzemi_*, 203110_BL_Cast_uzemi_*, atd.
- **resene_point**: 101111_BL_Resene_uzemi (bod řešeného území)
- **ostatní**: běžné vrstvy

Workflow:
1. Export všech jednotlivých vrstev
2. process_polylines_to_polygon() - zpracování polyline vrstev
3. perform_spatial_join_analysis() - spatial join bodů
4. split_analysis_by_layer() - rozdělení vrstev dle Layer atributu
5. extract_problem_polygons() - identifikace problémů
6. Mazání bodových vrstev a pomocnýchFC

### process_polylines_to_polygon()
Převádí polyline vrstvy na polygony se geometrickým čištěním.

Algoritmus:
```
1. Merge všech polyline vrstev
2. Snap hran k sobě (tolerance 0.3 m)
3. Feature to Polygon - vytvoření zaplněných polygonů
4. Vytvoření zvláštního polygonu z linie řešeného území
5. Merge obou typů polygonů
6. Integrate - geometrické vyčištění (0.3 m)
7. Select - oddělení finálních polygonů
```

Důvod duplikace: Hlavní polygon řešeného území je potřebný pro WITHIN analýzu

### perform_spatial_join_analysis()
Provádí spatial join bodů k polygonům s automatickým hodnocením.

Parametry SpatialJoin:
- join_operation: "JOIN_ONE_TO_ONE"
- join_type: "KEEP_ALL"
- match_option: "CONTAINS"

Hodnocení dle Join_Count:
```
Join_Count = 0 → "bez bodu"
Join_Count = 1 → "v pořádku"
Join_Count > 1 → "více bodů"
```

Výstup: vrstva s polem "bod" obsahujícím hodnocení

### split_analysis_by_layer()
Rozděluje vrstvu Resene_uzemi_with_Points dle hodnot v poli Layer.

Proces:
1. Načte unikátní hodnoty z pole Layer
2. Pro každou hodnotu vytvoří Select (Where_Clause)
3. Sanitizuje název Layer hodnoty
4. Přidá prefix (výchozí "Z")
5. Zajistí jedinečnost názvu

Příklad: Layer="202110_BL_Cast_uzemi_UP" → vrstva "Z202110_BL_Cast_uzemi_UP"

### extract_problem_polygons()
Vytváří samostatné vrstvy pro problematické prvky.

Vrstvy:
1. **ZPolygony_bez_bodu** - Join_Count = 0
2. **ZPolygony_vice_bodu** - Join_Count > 1
3. **ZPolygony_mimo_uzemi** - pozice_resene_uzemi = "mimo"

Každá vrstva se vytvoří pouze pokud obsahuje data.

### add_within_analysis()
Analyzuje, zda polygony leží uvnitř řešeného území (WITHIN).

Proces:
1. Vytvoří feature layer z target polygonů
2. Select by Location s parametrem "WITHIN"
3. Označí vybrané jako "uvnitř řešeného území"
4. Zbývající označí jako "mimo řešené území"

Pole "pozice_resene_uzemi" obsahuje výsledek.

## Geometrické operace

### Integrate
Operace pro čištění geometrie a odstranění drobných nepřesností.

Parametry:
- Tolerance: 0.3 metru
- Spojuje vrcholy vzdálené méně než 30 cm
- Odstraňuje drobné nerovnosti
- Může způsobit mírné posuny geometrie

Použití v procesu:
```python
arcpy.management.Integrate([all_polygons_temp], "0.3 Meters")
```

### Snap
Přichycení geometrie k referenčním prvkům.

Použití v procesu:
```python
snap_env = [[merged_fc, "EDGE", "0.3 Meters"]]
arcpy.edit.Snap(merged_fc, snap_env)
```

Parametry:
- Snap type: "EDGE" (přichycení k hranám)
- Tolerance: 0.3 m pro sloučení linií, 1.0 m pro přichycení

### Feature to Polygon
Konverzní operace, která vytváří polygony z linií.

Vytváří polygony ohraničené linií a vypouští obsah. Připojuje atributy původních linií. Používá se s parametrem attributes="ATTRIBUTES" pro zachování atributů.

### Spatial Join
Prostorové spojení s metodou CONTAINS.

```python
arcpy.analysis.SpatialJoin(
    target_features=polygon_fc,
    join_features=merged_points_fc,
    out_feature_class=final_join_fc,
    join_operation="JOIN_ONE_TO_ONE",
    join_type="KEEP_ALL",
    match_option="CONTAINS"
)
```

Výsledek obsahuje pole Join_Count s počtem připojených bodů.

## Správa prostředků

### Dočasné prostředky
Tool používá in_memory workspace pro dočasné vrstvy:

```python
temp_polygon = "in_memory\\temp_polygon"
temp_join = "in_memory\\temp_join"
all_polygons_temp = "in_memory\\all_polygons_temp"
```

Výhody in_memory:
- Rychlejší zpracování (RAM vs disk)
- Automatické čištění po ukončení
- Menší nároky na diskové místo
- Ideální pro mezivýsledky

Čištění:
```python
arcpy.Delete_management(temp_polygon)
arcpy.Delete_management(temp_join)
```

### Mazání nevyužitých vrstev
Po zpracování se automaticky mažou:
- Bodové vrstvy (point_layers_for_join)
- Bod řešeného území (resene_point_fc)
- Původní polygony (nahrazeny splitnutými vrstvami)
- Originální analýza vrstva (nahrazena split výsledky)

## Error handling a logování

### Strategie zacházení s chybami
Každá kritická operace je obalena try-except blokem:

```python
try:
    result = arcpy.operation()
    if result:
        exported_layers.append(result)
except Exception as e:
    arcpy.AddError(f"[method_name] Chyba: {e}")
    return None
```

### Logování
Všechny operace se logují na tři úrovně:

```python
arcpy.AddMessage(f"[method] Informace")      # Info zpráva
arcpy.AddWarning(f"[method] Varování")       # Upozornění
arcpy.AddError(f"[method] Chyba")            # Chybová zpráva
```

Prefix v hranatých závorkách identifikuje, ze které metody zpráva pochází.

### Typické chyby
- RuntimeError: Neplatná geometrie, chybějící FC
- TypeError: Nekompatibilní datové typy, chybné parametry
- OSError: Nedostatek místa na disku, přístupová práva
- ValueError: Neplatné hodnoty parametrů

## Optimalizace a pokročilé použití

### Výkonnostní tipy
- Používejte SSD disk pro geodatabázi
- Minimalizujte ostatní aplikace během zpracování
- Pro CAD > 100 MB zvažte rozdělení do menších částí
- Nastavte odpovídající XY tolerance a resolution

### Možná vylepšení
- Implementace paralelizace pro vícejádrové procesory
- Caching layer metadata pro opakované běhy
- Podpora pro WFS/WMS zdroje
- GUI pro konfiguraci bez editace kódu

### Rozšíření
Toolbox je napsán modulárně a lze ho snadno rozšířit:
- Přidání nových metod do CadFile třídy
- Definování nových kategorií vrstev
- Vytvoření vlastního ExportLayer s jinými parametry

## Kontrola kvality výstupu

### Validace výsledků
Po spuštění toolboxu ověřte:
1. Počet vrstev v geodatabázi
2. Atributy vrstev (pole "bod", "pozice_resene_uzemi")
3. Hodnoty v polích (správné kategorizace)
4. Geometrickou validitu (polygony bez děr, linky bez zalomení)
5. Souřadnicový systém

### Debugging
V případě problémů:
1. Zkontrolujte logy v ArcGIS Pro (okno Messages)
2. Ověřte data v CAD souboru
3. Zkontrolujte geodatabázi na korumpované vrstvy
4. Spusťte tool s Debug nastavením (úprava kódu)

---
Poslední aktualizace: Říjen 2025
