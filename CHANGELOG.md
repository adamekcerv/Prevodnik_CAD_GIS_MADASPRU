# Changelog

Všechny významné změny v CAD to GIS Import Toolbox projektu budou zdokumentovány v tomto souboru.

## [2.0.0] - 2025-10-20

### Přidáno
- **Nový převodník výšek** (`Prevodnik_CAD_GIS_Vysky.pyt`)
  - Specializovaný na stavební čáry (SC) a výškové rozhraní (VR)
  - Pokročilé rozdělení bufferů pomocí kolmých řezných čar
  - PolygonToCenterline funkce s Foundation extension
  - AlignFeatures pro srovnání geometrie s původními liniemi
  - Zachování specifických atributů výškových regulativů (VYSKA_VB_12, NP_MIN_12, atd.)
- **Workflow diagramy** v Mermaid syntaxi pro oba převodníky

### Změněno
- **Přejmenování původního převodníku** z `Prevodnik_CAD_GIS_Madaspru.pyt` na `Prevodnik_CAD_GIS_ReseneUzemi.pyt`
- **Aktualizované toolbox labels** pro lepší rozlišení:
  - "CAD Import Tools - Řešená území" (původní)
  - "MADASPRU CAD Import - Výšky" (nový)
- **Kompletně přepsaná dokumentace** s pokrytím obou převodníků
- **Odstraněny emoji z dokumentace** pro profesionální vzhled
- **Nová struktura README.md** s jasným rozdělením funkcionalit

### Struktura souborů
```
Resene_uzemi/
├── Prevodnik_CAD_GIS_ReseneUzemi.pyt    # Převodník řešených území
├── Prevodnik_CAD_GIS_Vysky.pyt          # Převodník výšek  
├── README.md                             # Kompletní dokumentace
├── README_Vysky.md                       # Stručná dokumentace výšek
├── TECHNICAL_DOCS.md                     # Technická dokumentace
└── CHANGELOG.md                          # Historie změn
```

### Technické vylepšení
- **Společná funkce `generate_unique_name()`** pro oba převodníky
- **Rozšířené logování** s prefixováním zpráv
- **Fallback strategie** pro pokročilé geometrické operace
- **Foundation extension detection** s graceful degradation

---

## [1.0.0] - 2025-09-01

### Přidáno
- ✅ **Základní import CAD vrstev** - podporované formáty DWG, DXF, DGN
- ✅ **Automatické předvybrání specifických vrstev** - inteligentní detekce a výběr relevantních vrstev
- ✅ **Pokročilé zpracování polyline vrstev**:
  - Automatické spojování (merge) linií řešeného území a částí území
  - Převod na polygony pomocí Feature to Polygon
  - Geometrické čištění pomocí Integrate (tolerance 30 cm)
- ✅ **Spatial join analýza bodových vrstev**:
  - Prostorové připojení bodů k polygonům
  - Automatické hodnocení kvality dat
  - Statistické výstupy
- ✅ **Snap operace pro přichycení linií**:
  - Přichycení původních linií k finálním polygonům
  - Zachování geometrické konzistence
  - Tolerance 1 metr
- ✅ **Hodnocení kvality dat**:
  - Pole "bod" s hodnocením: "v pořádku", "bez bodu", "více bodů"
  - Automatické počítání a klasifikace
  - Reportování statistik

### Specifické vrstvy
- **101110_PL_Resene_uzemi** (Polyline) - řešené území
- **200000_PL_Cast_uzemi** (Polyline) - části území  
- **101111_BL_Resene_uzemi** (Point) - kontrolní bod řešeného území
- **202110_BL_Cast_uzemi_UP** (Point) - územní plán
- **203110_BL_Cast_uzemi_SB** (Point) - stavební bloky
- **204110_BL_Cast_uzemi_NB** (Point) - nadzemní budovy
- **205110_BL_Cast_uzemi_XB** (Point) - ostatní budovy

### Výstupní vrstvy
- **Resene_uzemi_with_Points** - polygonová vrstva s analýzou bodů Cast_uzemi
- **Resene_uzemi_Snapped** - liniová vrstva s atributy bodu Resene_uzemi
- **Původní vrstvy** - všechny importované vrstvy zachovány pro referenci

### Technické funkce
- **Automatická detekce souřadnicových systémů** z CAD souborů
- **Podpora reprojekce** s možností transformace
- **Vytváření Feature Datasetů** s custom tolerance a resolution
- **Unikátní pojmenování** - automatická prevence konfliktů názvů
- **Rozsáhlé logování** - detailní zprávy o průběhu zpracování
- **Error handling** - robustní zacházení s chybami

### Optimalizace
- **In-memory workspace** pro dočasné operace
- **Automatické čištění** dočasných dat
- **Efektivní správa paměti**

### Dokumentace
- **README.md** - kompletní uživatelská dokumentace
- **TECHNICAL_DOCS.md** - technická dokumentace
- **Mermaid flowchart** - vizualizace workflow
- **Troubleshooting guide** - řešení běžných problémů

---

## Legenda typů změn
- **Přidáno** - nové funkce
- **Změněno** - změny v existující funkcionalitě  
- **Odstraněno** - odebrané funkce
- **Opraveno** - opravy chyb
- **Technické** - technické vylepšení
- **Struktura** - změny ve struktuře souborů
- **Dokumentace** - aktualizace dokumentace
- **Optimalizace** - výkonnostní vylepšení

## [0.9.0] - 2025-08-30 (Pre-release)

### Přidáno
- Základní struktura toolboxu
- Export CAD vrstev do geodatabáze
- Automatické pojmenování výstupních vrstev

### Opraveno
- Problémy s jedinečností názvů feature classes
- Chyby při spatial join operacích

## [0.8.0] - 2025-08-29 (Alpha)

### Přidáno
- Původní verze toolboxu s rozšířenými funkcemi
- Komplexní workflow pro různé typy projektů

### Odebrané
- Složité funkce nespecifické pro MADASPRU projekt
- Zbytečné parametry a konfigurace

---

## Typy změn
- **Přidáno** - pro nové funkce
- **Změněno** - pro změny v existujících funkcích  
- **Zastaralé** - pro funkce, které budou brzy odstraněny
- **Odstraněno** - pro nyní odstraněné funkce
- **Opraveno** - pro opravy chyb
- **Bezpečnost** - pro bezpečnostní záplaty
