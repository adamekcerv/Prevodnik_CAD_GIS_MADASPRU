# CAD Import Toolbox - Převodník Výšek

Python toolbox pro ArcGIS Pro specializovaný na import a zpracování **výškových regulativů** z CAD dat.

## 🎯 Účel

Tento převodník je určen pro zpracování **stavebních čar (SC)** a **výškových rozhraní (VR)** s automatickým vytváření centerline linií se zachováním atributů výšek.

## 📥 Vstupní vrstvy (MADASPRU)

### Stavební čáry (SC)
- `301110_PL_SC_uzavrena`
- `301111_PL_SC_polouzavrena` 
- `301112_PL_SC_otevrena`
- `301113_PL_SC_volna`
- `301114_PL_SC_bez_rozliseni`
- `301115_PL_SC_jina_XX`

### Výškové rozhraní (VR)
- `302210_BL_VR_na_linii` (kruhy)
- `302211_PL_VR_na_linii_rozhrani` (linie rozhraní)

## 🏗️ Proces zpracování

1. **Export a merge** všech SC vrstev do jedné
2. **Snap VR rozhraní** na SC linie (tolerance 30 cm)
3. **Intersect** → vytvoří bodovou vrstvu průsečíků
4. **Pokročilé rozdělení** SC podle rozhraní:
   - FeatureToLine → topologicky čisté segmenty
   - Buffer 30 cm ze spojených linií
   - Kolmé řezné čáry v místech rozhraní
   - Přesné rozdělení pomocí FeatureToPolygon
5. **Zpracování VR kruhů** - filtrování uzavřených linií
6. **Spatial Join** bufferu s kruhy
7. **PolygonToCenterline** → vytvoří finální centerline
8. **AlignFeatures** → srovná geometrii s původními liniemi

## 📊 Hlavní výstup

### `PL_SC_centerline_LN`
Finální centerline linie s atributy výšek:
- **Layer**, **VYSKA_VB_12**, **VYSKA_VB_I_12** 
- **NP_MIN_12**, **NP_MAX_12**, **NUP_MAX_12**
- **RIMSA_MIN_12**, **RIMSA_MAX_12**, **VYSKA_MAX_12**
- **NAZEV_BLOK_12**, **DOK_NAZEV_12**, **VYSKA_VB_D_12**
- **OZNACENI_12**, **DRUH_UP_12**, **DRUH_INFO_12**, **PODTYP_12**

## ⚙️ Požadavky

- **ArcGIS Pro 2.8+**
- **Foundation/Production Mapping extension** (pro PolygonToCenterline)
- **S-JTSK souřadnicový systém** (EPSG:5514)

## 🚀 Použití

1. Přidejte toolbox do ArcGIS Pro
2. Spusťte **"Import CAD vrstev (Výšky)"**
3. Vyberte CAD soubor - vrstvy se automaticky předvyberou
4. Nastavte výstupní geodatabázi
5. Spusťte proces

## 🔧 Speciální funkce

- **Kolmé řezné čáry** - automaticky generované pro přesné rozdělení
- **Inteligentní filtering** - pouze platné buffery s liniemi
- **Geometrické srovnání** - align centerline s původními liniemi
- **Fallback strategie** - při chybách použije jednodušší metody

## 📋 Výstupní logy

Sledujte zprávy v ArcGIS Pro:
- `SC linie snapped na sebe navzájem`
- `Vytvořeno X kolmých řezných čar`
- `Buffer přesně rozdělen kolmicemi na X částí`
- `Centerline vytvořena s X prvky`
- `Geometrie centerline srovnána s původními liniemi`

---

**Pro kompletní dokumentaci** viz hlavní `README.md` v této složce.

**Verze**: 2.0 (Výšky)  
**Licence**: MIT