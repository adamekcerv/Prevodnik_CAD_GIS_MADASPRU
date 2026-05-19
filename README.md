# CAD to GIS Import Toolbox – MADASPRU

Python toolboxy pro ArcGIS Pro určené pro import a zpracování CAD dat územních plánů MADASPRU. Hlavní toolbox spustí v jednom kroku kompletní import – řešená území i výšková regulace – a vše exportuje do jednoho společného datasetu.

## Struktura souborů

```
Prevodnik_CAD_GIS.pyt                  ← hlavní toolbox (jeden kombinovaný nástroj)
Prevodnik_CAD_GIS_ReseneUzemi.pyt      ← dílčí modul: řešená území
Prevodnik_CAD_GIS_Vysky.pyt            ← dílčí modul: výšková regulace
madaspru_reseneuzemi_config.json       ← konfigurace datového modelu (řešená území)
madaspru_vysky_config.json             ← konfigurace datového modelu (výšky)
```

> Všechny tři soubory musí být ve stejné složce. Hlavní toolbox dynamicky načítá kód z dílčích modulů.

---

## Hlavní toolbox – Prevodnik_CAD_GIS.pyt

### Nástroj: Import CAD do GIS (Řešená území + Výšky)

Jeden nástroj spustí za sebou dva workflow a výsledky uloží do jedné geodatabáze / Feature Datasetu.

### Parametry

| # | Název | Typ | Popis |
|---|-------|-----|-------|
| 0 | Input CAD Soubor | Soubor (.dwg/.dxf/.dgn) | Zdrojový CAD soubor |
| 1 | CAD Vrstvy | Text, více hodnot | Automaticky předvyplněno; lze upravit |
| 2 | Output Geodatabáze | File GDB | Cílová GDB |
| 3 | Output Feature Dataset | Text (volitelné) | Název FD; pokud neexistuje, vytvoří se |
| 4 | XY Tolerance (m) | Číslo | Výchozí: 0,01 m |
| 5 | XY Resolution (m) | Číslo | Výchozí: 0,001 m |

**Hardcoded hodnoty** (nelze měnit parametrem):
- Souřadnicový systém: **S-JTSK / Krovak East North (EPSG 5514)**
- Prefix výstupů: **`Z_`**
- Split radius: **0,001 m** (min. 0,3 m pro CAD větev)

### Použití

1. ArcGIS Pro → Catalog Pane → Toolboxes → Add Toolbox
2. Vyberte `Prevodnik_CAD_GIS.pyt`
3. Otevřete nástroj **Import CAD do GIS (Řešená území + Výšky)**
4. Vyplňte parametry → Run

### Celkový workflow

```mermaid
flowchart TD
    subgraph INPUT["Vstup"]
        DWG[CAD soubor\n.dwg / .dxf]
    end

    subgraph KROK1["KROK 1 – Řešená území"]
        direction TB
        K1A[Export polyline a bodových vrstev]
        K1B[Merge + Snap 30 cm → FeatureToPolygon]
        K1C[Integrate polygonů 30 cm]
        K1D[Rozdělení podle rozhraní VR kruhů 302311]
        K1E[Spatial Join bodů 202110–205110]
        K1F[Analýza Within vůči řešenému území]
        K1G[Split podle Layer → finalizace atributů]
        K1A --> K1B --> K1C --> K1D --> K1E --> K1F --> K1G
    end

    subgraph KROK2["KROK 2 – Výšková regulace"]
        direction TB
        K2A[Import SC linií + VR bloků]
        K2B[Průsečíky rozhraní 302211 × SC]
        K2C[První řezání SC]
        K2D[Spatial Join VR bloků k segmentům]
        K2E[Dogenerování chybějících rozhraní]
        K2F[Finální řezání všemi rozhraními]
        K2G[Čištění falešných řezů]
        K2H[Propagace atributů s respektováním rozhraní]
        K2I[Export výstupních vrstev]
        K2A --> K2B --> K2C --> K2D --> K2E --> K2F --> K2G --> K2H --> K2I
    end

    subgraph OUTPUT["Výstup – jedna GDB / Feature Dataset"]
        O1[Z_1011_ReseneUzemi_p]
        O2[Z_2011_UlicniCara_l]
        O3[Z_2021_UlicniProstranstvi_p]
        O4[Z_2031_StavebniBlok_p]
        O5[Z_2041_NestavebniBlok_p]
        O6[Z_2051_JinaCastUzemi_p]
        O7[Z_3023_VyskovaRegulaceNaPlochu_p]
        O8[Z_3011_StavebniCara_l]
        O9[Z_3022_VyskovaRegulaceNaLinii_l]
        O10[Z_3021_VyskovaRegulaceNaBod_b]
    end

    DWG --> KROK1
    DWG --> KROK2
    KROK1 --> O1 & O2 & O3 & O4 & O5 & O6 & O7
    KROK2 --> O8 & O9 & O10

    style INPUT fill:#e3f2fd,stroke:#90caf9
    style KROK1 fill:#f3e5f5,stroke:#ce93d8
    style KROK2 fill:#e8f5e9,stroke:#a5d6a7
    style OUTPUT fill:#fff9c4,stroke:#f9a825
```

---

## Krok 1 – Řešená území (detail)

### Vstupní CAD vrstvy

| CAD vrstva | Typ | Popis |
|------------|-----|-------|
| 101110_PL_Resene_uzemi | Polyline | Hranice řešeného území |
| 200000_PL_Cast_uzemi | Polyline | Hranice částí území |
| 201110_PL_Ulicni_cara | Polyline | Ulični čáry |
| 101111_BL_Resene_uzemi | Point | Referenční bod řešeného území |
| 202110_BL_Cast_uzemi_UP | Point | Bloky uličních prostranství |
| 203110_BL_Cast_uzemi_SB | Point | Bloky stavebních bloků |
| 204110_BL_Cast_uzemi_NB | Point | Bloky nestavebních bloků |
| 205110_BL_Cast_uzemi_XB | Point | Bloky jiných částí území |
| 302310_BL_VR_na_plochu | Polyline | Výšková regulace na plochu (kruhy) |
| 302311_PL_VR_na_plochu_rozhrani | Polyline | Rozhraní výškových kruhů |

### Výstupní vrstvy

| Výstupní vrstva | Typ | Popis |
|-----------------|-----|-------|
| Z_1011_ReseneUzemi_p | Polygon | Polygon řešeného území |
| Z_2011_UlicniCara_l | Polyline | Ulični čáry |
| Z_2021_UlicniProstranstvi_p | Polygon | Ulični prostranství |
| Z_2031_StavebniBlok_p | Polygon | Stavební bloky |
| Z_2041_NestavebniBlok_p | Polygon | Nestavební bloky |
| Z_2051_JinaCastUzemi_p | Polygon | Jiné části území |
| Z_3023_VyskovaRegulaceNaPlochu_p | Polygon | Výšková regulace na plochu |

### Workflow detail

```mermaid
flowchart TD
    PL_RU[101110 Polyline\nŘešené území] --> MERGE
    PL_CU[200000 Polyline\nČásti území] --> MERGE
    PL_UC[201110 Polyline\nUlični čáry] --> MERGE

    MERGE[Merge + Snap EDGE 30cm] --> F2P[FeatureToPolygon]
    F2P --> INTEGRATE[Integrate 30cm]
    
    VR_ROZH[302311 Rozhraní\nVR kruhů] --> SPLIT_VR[Rozdělení polygonů\npodle rozhraní]
    INTEGRATE --> SPLIT_VR

    PT_UP[202110 Point UP] --> SJ
    PT_SB[203110 Point SB] --> SJ
    PT_NB[204110 Point NB] --> SJ
    PT_XB[205110 Point XB] --> SJ
    SPLIT_VR --> SJ[Spatial Join CONTAINS\nbody → polygony]
    SJ --> WITHIN[Analýza Within\nvůči hlavnímu polygonu RÚ]
    
    VR_KRUHY[302310 VR kruhy] --> CENTROIDS[Centroidy kruhů]
    CENTROIDS --> SJ2[Spatial Join\nVR atributy → polygony]
    WITHIN --> SJ2
    
    SJ2 --> SPLIT_L[Split podle pole Layer]
    SPLIT_L --> FINALIZE[Finalizace atributů\ndle datového modelu]
    FINALIZE --> OUT[Výstupní vrstvy\nZ_2021, Z_2031, Z_2041, Z_2051\nZ_3023, Z_1011, Z_2011]

    style MERGE fill:#e1f5ff
    style OUT fill:#c8e6c9
    style VR_ROZH fill:#fff9c4
    style VR_KRUHY fill:#fff9c4
```

---

## Krok 2 – Výšková regulace (detail)

### Vstupní CAD vrstvy

| CAD vrstva | Typ | Popis |
|------------|-----|-------|
| 3011xx_PL_SC_* | Polyline | Stavební čáry (uzavřená, polouzavřená, otevřená, volná, bez rozlišení, jiná) |
| 302210_BL_VR_na_linii | Polyline | VR bloky na linii (zdroj výškových atributů) |
| 302211_PL_VR_na_linii_rozhrani | Polyline | Rozhraní VR na linii (bariéry propagace) |
| 302110_BL_VR_na_bod | Polyline | VR bloky na bod |

### Výstupní vrstvy

| Výstupní vrstva | Typ | Popis |
|-----------------|-----|-------|
| Z_3011_StavebniCara_l | Polyline | Stavební čáry dle typu (pole DRUH_SC) |
| Z_3022_VyskovaRegulaceNaLinii_l | Polyline | Výšková regulace na linii s atributy |
| Z_3021_VyskovaRegulaceNaBod_b | Point | Výšková regulace na bod |

### Výškové atributy (Z_3022)

`VYSKA_VB` · `VYSKA_VB_I` · `NP_MIN` · `NP_MAX` · `NPU_MAX` · `RIMSA_MIN` · `RIMSA_MAX` · `VYSKA_MAX`

### Workflow detail

```mermaid
flowchart TD
    SC_LN[3011xx SC Linie] --> IMPORT
    VR_BL[302210 VR Bloky] --> IMPORT
    VR_RZ[302211 Rozhraní] --> IMPORT
    VR_BOD[302110 VR na bod] --> IMPORT

    IMPORT[Fáze 1: Import + Merge SC\ns polem SC_TYPE] --> F2[Fáze 2: Průsečíky\nrozhraní × SC → body]
    F2 --> F3[Fáze 3: První řezání SC\ndle CAD rozhraní]
    F3 --> F4[Fáze 4: Spatial Join\nVR bloků k segmentům]
    F4 --> F5[Fáze 5: Dogenerování\nchybějících rozhraní]
    F5 --> F6[Fáze 6: Finální řezání\nvšemi rozhraními]
    F6 --> F7[Fáze 7: Čištění\nfalešných řezů]
    F7 --> F8A

    subgraph F8["Fáze 8: Propagace atributů"]
        F8A[CAD větev\niterativní přelévání\ns respektem rozhraní]
        F8B[NOCAD větev\nunikátní párování\ndo 0,3 m]
        F8C[Merge CAD + NOCAD]
        F8A --> F8C
        F8B --> F8C
    end

    F8C --> F9[Fáze 9: Export\ndle datového modelu]
    F9 --> SC_OUT[Z_3011_StavebniCara_l]
    F9 --> VR_OUT[Z_3022_VyskovaRegulaceNaLinii_l]
    VR_BOD --> F9
    F9 --> BOD_OUT[Z_3021_VyskovaRegulaceNaBod_b]

    style IMPORT fill:#e1f5ff
    style F8 fill:#fff9c4
    style SC_OUT fill:#c8e6c9
    style VR_OUT fill:#c8e6c9
    style BOD_OUT fill:#c8e6c9
```

---

## Instalace

### Požadavky
- **ArcGIS Pro** 2.8+
- Standardní Python prostředí `arcgispro-py3`
- Žádné externí knihovny

### Postup
1. Zkopírujte všechny `.pyt` a `.json` soubory do jedné složky
2. V ArcGIS Pro: Catalog Pane → Toolboxes → Add Toolbox → vyberte `Prevodnik_CAD_GIS.pyt`
3. Spusťte nástroj **Import CAD do GIS (Řešená území + Výšky)**

---

## Řešení problémů

| Problém | Příčina | Řešení |
|---------|---------|--------|
| Výstupní vrstvy mají suffix `_1`, `_2`... | Vrstvy stejného jména již existují v GDB | Použijte čistou GDB nebo jiný Feature Dataset |
| Chybějící atributy u SC linií | VR kruh (302210) neprotíná linii nebo chybí rozhraní (302211) | Zkontrolujte topologii v CADu |
| Atributy přetekly kam neměly | Chybí rozhraní (302211) na hranici výškového pásma | Doplňte linii rozhraní do CADu |
| Polygony nemají body | Body (202110–205110) neleží uvnitř polygonu | Zkontrolujte polohu bodů v CADu |

---

## Konfigurace datového modelu

Konfigurace je uložena v JSON souborech ve stejné složce jako toolboxy. Python kód ji načte při startu a použije místo hardcoded hodnot. Pokud soubor chybí nebo je poškozený, nástroj spadne zpět na výchozí hodnoty a zobrazí varování v logu.

### madaspru_reseneuzemi_config.json

Řídí chování nástroje Řešená území:

| Klíč | Popis |
|------|-------|
| `field_schema` | Typy, délky a aliasy výstupních polí (19 polí) |
| `height_attributes` | Seznam výškových atributů |
| `output_layers` | Definice výstupních vrstev — SKNAZEV, OBTYPNAZEV, povolené atributy, cílový název |
| `domain_allowed_values` | Povolené hodnoty pro DRUH_UP, DRUH_SC, VYSKA_VB |
| `domains` | Definice domén pro import do GDB |

### madaspru_vysky_config.json

Řídí chování nástroje Výšková regulace:

| Klíč | Popis |
|------|-------|
| `field_schema` | Typy a délky výstupních polí |
| `height_attributes` | Seznam výškových atributů |
| `vr_attribute_aliases` | Mapování alternativních názvů polí z CAD bloků |
| `output_layers` | Definice vrstev Z_3011, Z_3021, Z_3022 |
| `domain_allowed_values` | Povolené hodnoty pro DRUH_SC, VYSKA_VB |
| `domains` | Definice domén pro import do GDB |
| `sc_druh_mapping` | Mapování čísla CAD vrstvy → kód DRUH_SC |
| `processing` | Procesní parametry (tolerance NOCAD větve) |

### Jak upravit konfiguraci

Příklad — přidat novou povolenou hodnotu pro DRUH_SC:

```json
"domain_allowed_values": {
    "DRUH_SC": ["SCU", "SCPU", "SCO", "SCV", "SC", "SCX", "SCN"]
}
```

Příklad — přidat nové výstupní pole:

```json
"field_schema": {
    "POZNAMKA": {"type": "TEXT", "length": 500, "alias": "POZNAMKA"}
}
```

Změny se projeví při příštím spuštění nástroje — není třeba editovat `.pyt` soubory.

---

*Aktualizováno: Květen 2026*
