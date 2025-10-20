# Changelog

Všechny významné změny v tomto projektu budou dokumentovány v tomto souboru.

Formát vychází z [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
a tento projekt dodržuje [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- 📖 **README.md** - kompletní uživatelská dokumentace
- 🔧 **TECHNICAL_DOCS.md** - technická dokumentace
- 📋 **Mermaid flowchart** - vizualizace workflow
- 🐛 **Troubleshooting guide** - řešení běžných problémů

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
