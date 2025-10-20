# CAD to GIS Import Toolbox

Python toolbox pro ArcGIS Pro určený pro import a zpracování CAD dat s automatickou analýzou řešených území.

## Přehled

Toolbox automatizuje import CAD souborů (DWG, DXF, DGN) do geodatabáze s automatickým zpracováním:
- Převod polyline vrstev do polygonů se geometrickým čištěním
- Prostorová analýza bodových vrstev a jejich propojení s polygony
- Automatické vyčištění geometrie s tolerancí 30 cm (integrate operace)
- Vytváření samostatných vrstev dle typu vrstvy a detekce problematických prvků

## Hlavní funkce

### Automatické zpracování vrstev
- **101110_PL_Resene_uzemi** (Polyline) - hranice řešeného území
- **200000_PL_Cast_uzemi** (Polyline) - hranice částí území
- **101111_BL_Resene_uzemi** (Point) - kontrolní bod řešeného území
- **202110_BL_Cast_uzemi_UP** (Point) - body územního plánu
- **203110_BL_Cast_uzemi_SB** (Point) - body stavebních bloků
- **204110_BL_Cast_uzemi_NB** (Point) - body nadzemních budov
- **205110_BL_Cast_uzemi_XB** (Point) - body ostatních objektů

### Zpracování polygonů
- Merge všech polyline vrstev s přichycením (snap) hran
- Převod na polygony (Feature to Polygon)
- Geometrické vyčištění (Integrate) s tolerancí 0.3 m
- Vytvoření zaplněných polygonů z linií

### Prostorová analýza
- Spatial join bodů k polygonům
- Automatické hodnocení kvality ("v pořádku", "bez bodu", "více bodů")
- Detekce polygonů mimo řešené území (WITHIN analýza)
- Vytvoření samostatných vrstev pro problematické prvky

## Instalace

### Požadavky
- ArcGIS Pro 2.8 nebo novější
- Python 3.x (součást ArcGIS Pro)
- Licenční úroveň Standard nebo Advanced (pro některé funkce)

### Postup instalace
1. Stáhněte soubor `Prevodnik_CAD_GIS_Madaspru.pyt`
2. Zkopírujte do složky s vaším ArcGIS Pro projektem
3. V ArcGIS Pro přidejte toolbox:
   - Catalog Pane → Toolboxes → Add Toolbox
   - Vyberte `Prevodnik_CAD_GIS_Madaspru.pyt`

## Použití

### Základní workflow

```
CAD soubor → Načtení vrstev → Automatický výběr → Export a zpracování → Výsledné vrstvy
```

### Parametry toolboxu

| Parametr | Typ | Popis | Výchozí hodnota |
|----------|-----|-------|-----------------|
| Input CAD Soubor | DEFile | Cesta k CAD souboru (DWG, DXF, DGN) | - |
| CAD Vrstva(y) | GPString | Vrstvy pro zpracování (automaticky předvolené) | Auto |
| Output Geodatabáze | DEWorkspace | Cílová geodatabáze | Povinný |
| Output Feature Dataset | GPString | Cílový feature dataset (volitelný) | - |
| XY Tolerance | GPDouble | Tolerancia XY v metrech | 0.01 |
| XY Resolution | GPDouble | Rozlišení XY v metrech | 0.001 |
| Output Souřadnicový Systém | GPSpatialReference | Výstupní souřadnicový systém | Auto z CAD |
| Geographic Transformation | GPString | Transformace souřadnic (volitelná) | - |
| Prefix jména výstupu | GPString | Prefix pro názvy výstupních vrstev | Z |

### Spuštění toolboxu

1. Otevřete toolbox v ArcGIS Pro
2. Spusťte tool "Import CAD do GIS"
3. Nastavte parametry:
   - Vyberte CAD soubor
   - Zvolte výstupní geodatabázi
   - Volitelně nastavte feature dataset a další parametry
4. Spusťte tool - vrstvy se automaticky předvyberou
5. Ověřte výsledky v geodatabázi

## Výstupní vrstvy

### Polygonové vrstvy
- **ZResene_uzemi_PL** - zaplněné polygony vytořené z linií (veškeré části území)
- **Z202110_BL_Cast_uzemi_UP** - polygony filtrované podle Layer atributu
- **Z203110_BL_Cast_uzemi_SB** - polygony filtrované podle Layer atributu
- **Z204110_BL_Cast_uzemi_NB** - polygony filtrované podle Layer atributu
- **Z205110_BL_Cast_uzemi_XB** - polygony filtrované podle Layer atributu
- **ZResene_uzemi_Polygon_with_Points** - polygon řešeného území s analýzou bodu

### Vrstvy s problémovými prvky
- **ZPolygony_bez_bodu** - polygony bez připojeného bodu (Join_Count = 0)
- **ZPolygony_vice_bodu** - polygony s více připojenými body (Join_Count > 1)
- **ZPolygony_mimo_uzemi** - polygony mimo hranice řešeného území

### Ostatní vrstvy
- **Z101110_PL_Resene_uzemi_LN** - původní linie řešeného území (zachované)
- **Z200000_PL_Cast_uzemi_LN** - původní linie částí území (zachované)
## Hodnocení kvality dat

### Pole "bod" - status bodů
| Hodnota | Podmínka | Popis |
|---------|----------|-------|
| v pořádku | Join_Count = 1 | Prvek má přiřazen právě jeden bod |
| bez bodu | Join_Count = 0 | Prvek nemá žádný připojený bod |
| více bodů | Join_Count > 1 | Prvek má připojeno více bodů |

### Pole "pozice_resene_uzemi" - poloha vůči řešenému území
| Hodnota | Popis |
|---------|-------|
| uvnitř řešeného území | Polygon leží kompletně uvnitř hranic řešeného území |
| mimo řešené území | Polygon leží mimo hranice řešeného území |

## Konfigurace

### Tolerance a rozlišení
- **XY Tolerance**: 0.01 m (standardní nastavení)
- **XY Resolution**: 0.001 m (milimetrová přesnost)
- **Integrate Tolerance**: 0.3 m (vyčištění geometrie)
- **Snap Tolerance**: 1.0 m (přichycení linií k polygonům)

### Souřadnicový systém
Toolbox automaticky detekuje souřadnicový systém z CAD souboru. Pokud není dostupný, používá S-JTSK (EPSG:5514). Podporuje automatickou reprojekci při změně cílového systému.

## Základní postup

1. Příprava CAD souboru
   - Zajistěte, že CAD obsahuje požadované vrstvy
   - Ověřte souřadnicový systém v CAD souboru

2. Spuštění toolboxu
   - Otevřete ArcGIS Pro
   - Přidejte toolbox: Catalog Pane → Add Toolbox
   - Spusťte "Import CAD do GIS"

3. Nastavení parametrů
   - Vyberte CAD soubor
   - Zvolte cílovou geodatabázi
   - Volitelně nastavte feature dataset a jiné parametry
   - Zkontrolujte automaticky předvolené vrstvy

4. Spuštění procesu
   - Klikněte Run
   - Sledujte průběh v Progress panelu
   - Ověřte výsledky v Catalog panelu

## Řešení problémů

### Chyby při spuštění

**"ERROR 000732: Target Workspace: Dataset does not exist"**
- Zkontrolujte cestu k geodatabázi
- Ověřte přístupová práva k složce

**"ERROR 000354: The name contains invalid characters"**
- Názvy vrstev se automaticky sanitizují
- Zvláštní znaky se nahrazují podtržítkem

**Prázdné výsledky**
- Ověřte, že CAD soubor obsahuje požadované vrstvy
- Zkontrolujte, že vrstvy obsahují data
- Ověřte souřadnicový systém

### Výstupní logy
Toolbox poskytuje detailní informace v okně zpráv:
- [export] - informace o exportu jednotlivých vrstev
- [process_polylines_to_polygon] - zpracování polyline vrstev
- [perform_spatial_join_analysis] - výsledky prostorové analýzy
- [split_analysis_by_layer] - rozdělení vrstev podle atributu
- [add_within_analysis] - analýza polohy vůči řešenému území

## Výkonnost

Doporučená konfigurace pro optimální výkon:
- Použijte SSD disk pro geodatabázi
- Minimalizujte ostatní procesy během zpracování
- Pro CAD soubory > 100 MB zvažte rozdělení na menší části
- Typicky trvá zpracování 2-10 minut dle rozsahu dat

## Novinky v poslední verzi

- Automatické splitování vrstev podle Layer atributu
- Vytváření vrstev s problematickými prvky
- Automatické mazání bodových vrstev po analýze
- Detekce polygonů mimo řešené území
- Normalizace názvů s prefixem Z

## Licence

MIT License

---
Poslední aktualizace: Říjen 2025
