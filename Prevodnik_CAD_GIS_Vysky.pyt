# -*- coding: utf-8 -*-
import arcpy
import os
import re

# Defaultní vrstvy pro MADASPRU project
DEFAULT_LAYERS = [
    "302110_BL_VR_na_bod",
    "302210_BL_VR_na_linii",
    "302211_PL_VR_na_linii_rozhrani"
]

# Výškové atributy pro dissolve a přenos (VYSKOVA_REGULACE_SPOLECNE_ATRIBUTY)
HEIGHT_ATTRIBUTES = [
    "VYSKA_VB", "VYSKA_VB_I",
    "NP_MIN", "NP_MAX", "NPU_MAX",
    "RIMSA_MIN", "RIMSA_MAX",
    "VYSKA_MAX"
]

VR_ATTRIBUTE_SOURCE_ALIASES = {
    "VYSKA_VB": ["VYSKAVB", "VR_VYSKA_VB", "VR_VYSKAVB", "VYSKA VB", "VYSKA_VB_D"],
    "VYSKA_VB_I": ["VYSKA_VBI", "VYSKAVBI", "VR_VYSKA_VB_I", "VR_VYSKA_VBI", "VYSKA VB I"],
    "NP_MIN": ["MIN_NP", "NPMIN", "VR_NP_MIN", "VR_NPMIN", "NP MIN"],
    "NP_MAX": ["MAX_NP", "NPMAX", "VR_NP_MAX", "VR_NPMAX", "NP MAX"],
    "NPU_MAX": ["NUP_MAX", "NPUMAX", "NUPMAX", "VR_NPU_MAX", "VR_NUP_MAX", "MAX_NPU", "MAX_NUP", "NPU MAX", "NUP MAX"],
    "RIMSA_MIN": ["MIN_RIMSA", "RIMSAMIN", "VR_RIMSA_MIN", "VR_RIMSAMIN", "RIMSA MIN", "RIMSA"],
    "RIMSA_MAX": ["MAX_RIMSA", "RIMSAMAX", "VR_RIMSA_MAX", "VR_RIMSAMAX", "RIMSA MAX"],
    "VYSKA_MAX": ["MAX_VYSKA", "VYSKAMAX", "VR_VYSKA_MAX", "VR_VYSKAMAX", "VYSKA MAX", "VYSKA", "VYSKA_TOTAL", "VYSKA_CELKEM"],
}

FIELD_SCHEMA = {
    "SKNAZEV": ("TEXT", 50),
    "OBTYPNAZEV": ("TEXT", 50),
    "ID_LOKAL": ("SHORT", None),
    "DRUH_SC": ("TEXT", 10),
    "DRUH_INFO": ("TEXT", 255),
    "VYSKA_VB": ("TEXT", 10),
    "VYSKA_VB_I": ("TEXT", 255),
    "NP_MIN": ("SHORT", None),
    "NP_MAX": ("SHORT", None),
    "NPU_MAX": ("SHORT", None),
    "RIMSA_MIN": ("FLOAT", None),
    "RIMSA_MAX": ("FLOAT", None),
    "VYSKA_MAX": ("FLOAT", None),
}

LAYER_MODEL_RULES = {
    "Z_3011_StavebniCara_l": {
        "constants": {
            "SKNAZEV": "regulace struktury",
            "OBTYPNAZEV": "stavební čára",
        },
        "required": ["SKNAZEV", "OBTYPNAZEV", "DRUH_SC", "ID_LOKAL"],
        "allowed": ["SKNAZEV", "OBTYPNAZEV", "DRUH_SC", "DRUH_INFO", "ID_LOKAL"],
    },
    "Z_3021_VyskovaRegulaceNaBod_b": {
        "constants": {
            "SKNAZEV": "regulace struktury",
            "OBTYPNAZEV": "výšková regulace na bod",
        },
        "required": ["SKNAZEV", "OBTYPNAZEV", "VYSKA_VB", "ID_LOKAL"],
        "allowed": ["SKNAZEV", "OBTYPNAZEV", "ID_LOKAL"] + HEIGHT_ATTRIBUTES,
    },
    "Z_3022_VyskovaRegulaceNaLinii_l": {
        "constants": {
            "SKNAZEV": "regulace struktury",
            "OBTYPNAZEV": "výšková regulace na linii",
        },
        "required": ["SKNAZEV", "OBTYPNAZEV", "VYSKA_VB", "ID_LOKAL"],
        "allowed": ["SKNAZEV", "OBTYPNAZEV", "ID_LOKAL"] + HEIGHT_ATTRIBUTES,
    },
}

DOMAIN_ALLOWED_VALUES = {
    "DRUH_SC": {"SCU", "SCPU", "SCO", "SCV", "SC", "SCX"},
    "VYSKA_VB": {"ST", "CH", "BPV", "VBX"},
}

DOMAIN_MODEL_DEFINITIONS = {
    "DRUH_SC": {
        "domain_name": "DRUH_STAVEBNI_CARY",
        "description": "Druh stavební čáry dle GIS modelu",
        "field_type": "TEXT",
        "coded_values": {
            "SCU": "stavební čára uzavřená",
            "SCPU": "stavební čára polouzavřená",
            "SCO": "stavební čára otevřená",
            "SCV": "stavební čára volná",
            "SC": "stavební čára bez rozlišení",
            "SCX": "stavební čára jiná",
        },
    },
    "VYSKA_VB": {
        "domain_name": "DRUH_VZTAZNEHO_BODU",
        "description": "Druh vztažného bodu dle GIS modelu",
        "field_type": "TEXT",
        "coded_values": {
            "ST": "nejnižší bod přilehlého stávajícího terénu",
            "CH": "nejnižší bod přilehlého chodníku",
            "BPV": "nula stupnice vodočtu Baltu po vyrovnání (Bpv)",
            "VBX": "vztažný bod jiný",
        },
    },
}

NOCAD_VR_ASSIGN_TOLERANCE_METERS = 0.30

# Mapování čísla CAD vrstvy na kód domény DRUH_STAVEBNI_CARY
SC_DRUH_MAPPING = {
    "301110": "SCU",   # stavební čára uzavřená
    "301111": "SCPU",  # stavební čára polouzavřená
    "301112": "SCO",   # stavební čára otevřená
    "301113": "SCV",   # stavební čára volná
    "301114": "SC",    # stavební čára bez rozlišení
    "301115": "SCX",   # stavební čára jiná
}

def get_druh_sc_from_sc_type(sc_type):
    """Vrátí kód DRUH_SC na základě názvu SC_TYPE (číslo vrstvy je prefix)."""
    if not sc_type:
        return None
    for prefix, druh in SC_DRUH_MAPPING.items():
        if str(sc_type).startswith(prefix):
            return druh
    return None

def generate_unique_name(gdb_path, base_name):
    """Generuje unikátní název pro feature class v geodatabázi"""
    unique_name = base_name
    counter = 1
    
    original_workspace = arcpy.env.workspace
    
    try:
        while arcpy.Exists(os.path.join(gdb_path, unique_name)):
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
        arcpy.env.workspace = original_workspace
    
    return unique_name


def log_message(message, level="INFO"):
    """Helper pro logování s úrovněmi"""
    prefix = {
        "INFO": "ℹ️",
        "OK": "✅",
        "WARN": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
        "STEP": "▶️",
        "CHECK": "📝"
    }.get(level, "")
    
    arcpy.AddMessage(f"{prefix} {message}")



def sanitize_name(name):
    """Odstraní nepovolené znaky z názvu"""
    if not name:
        return "unknown"
    return "".join(c if c.isalnum() else "_" for c in str(name))


def get_feature_count(fc):
    """Bezpečné získání počtu prvků"""
    try:
        return int(arcpy.GetCount_management(fc)[0])
    except:
        return 0


def _is_missing_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _generalize_field_type(field):
    if field.type == "SmallInteger":
        return "SHORT"
    if field.type in ["Integer", "Long"]:
        return "LONG"
    if field.type == "Single":
        return "FLOAT"
    if field.type == "Double":
        return "DOUBLE"
    if field.type == "String":
        return "TEXT"
    return field.type.upper()


def _field_requires_schema_fix(field, expected_type, expected_length=None):
    current_type = _generalize_field_type(field)
    if current_type != expected_type:
        return True

    if expected_type == "TEXT" and expected_length is not None:
        current_length = getattr(field, "length", None)
        if current_length != expected_length:
            return True

    return False


def _get_root_gdb_path(feature_class):
    try:
        workspace = arcpy.Describe(feature_class).path
    except Exception:
        return None

    if not workspace:
        return None

    if workspace.lower().endswith(".gdb"):
        return workspace

    parent = os.path.dirname(workspace)
    if parent and parent.lower().endswith(".gdb"):
        return parent

    return None


def _sync_coded_value_domain(root_gdb, domain_name, domain_def, existing_domain=None):
    existing_coded_values = {}
    if existing_domain is None:
        arcpy.management.CreateDomain(
            root_gdb,
            domain_name,
            domain_def["description"],
            domain_def["field_type"],
            "CODED"
        )
    else:
        existing_coded_values = dict(getattr(existing_domain, "codedValues", {}) or {})

    expected_coded_values = domain_def["coded_values"]

    for code, current_description in existing_coded_values.items():
        if expected_coded_values.get(code) != current_description:
            arcpy.management.DeleteCodedValueFromDomain(root_gdb, domain_name, code)

    for code, description in expected_coded_values.items():
        if existing_coded_values.get(code) != description:
            arcpy.management.AddCodedValueToDomain(root_gdb, domain_name, code, description)


def ensure_field_domain(feature_class, field_name):
    """Vytvoří a přiřadí coded-value doménu dle GIS modelu, pokud je definovaná."""
    domain_def = DOMAIN_MODEL_DEFINITIONS.get(field_name)
    if not domain_def or not feature_class or not arcpy.Exists(feature_class):
        return

    root_gdb = _get_root_gdb_path(feature_class)
    if not root_gdb or not arcpy.Exists(root_gdb):
        return

    try:
        existing_domains = {domain.name: domain for domain in arcpy.da.ListDomains(root_gdb)}
        domain_name = domain_def["domain_name"]

        _sync_coded_value_domain(
            root_gdb,
            domain_name,
            domain_def,
            existing_domains.get(domain_name)
        )

        arcpy.management.AssignDomainToField(feature_class, field_name, domain_name)
    except Exception as e:
        log_message(f"Nelze přiřadit doménu {field_name}: {e}", "WARN")


def _convert_value_to_type(value, expected_type):
    if _is_missing_value(value):
        return None

    if expected_type == "TEXT":
        return str(value)

    if isinstance(value, str):
        clean = value.lower().replace("m", "").replace(" ", "").replace(",", ".")
    else:
        clean = value

    if expected_type == "SHORT":
        return int(float(clean))
    if expected_type == "FLOAT":
        return float(clean)

    return value


def _normalize_field_key(value):
    if value is None:
        return ""
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def _is_zero_like_value(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        txt = value.strip().replace(",", ".")
        if txt == "":
            return False
        try:
            return float(txt) == 0.0
        except Exception:
            return False
    return False


def _iter_vr_attribute_aliases(target_attr):
    aliases = [target_attr] + VR_ATTRIBUTE_SOURCE_ALIASES.get(target_attr, [])
    expanded = []
    seen = set()

    for alias in aliases:
        variants = [alias, alias.replace("_", " "), alias.replace("_", "")]
        if not str(alias).upper().startswith("VR_"):
            variants.append(f"VR_{alias}")

        for variant in variants:
            key = str(variant).upper()
            if key not in seen:
                seen.add(key)
                expanded.append(variant)

    return expanded


def _find_matching_source_fields(field_names, target_attr):
    matches = []
    seen = set()
    normalized_aliases = [
        (idx, _normalize_field_key(alias))
        for idx, alias in enumerate(_iter_vr_attribute_aliases(target_attr))
        if _normalize_field_key(alias)
    ]

    for field_name in field_names:
        base_name = re.sub(r"_\d+$", "", field_name)
        normalized_base = _normalize_field_key(base_name)
        best_rank = None

        for alias_idx, normalized_alias in normalized_aliases:
            if normalized_base == normalized_alias:
                best_rank = (0, alias_idx, len(base_name))
                break
            if normalized_base.endswith(normalized_alias):
                candidate_rank = (1, alias_idx, len(base_name))
                if best_rank is None or candidate_rank < best_rank:
                    best_rank = candidate_rank

        if best_rank is not None and field_name not in seen:
            seen.add(field_name)
            matches.append((best_rank, field_name))

    matches.sort(key=lambda item: item[0])
    return [field_name for _, field_name in matches]


def _ensure_field_type(feature_class, field_name, expected_type, expected_length=None):
    fields = {f.name: f for f in arcpy.ListFields(feature_class)}

    if field_name not in fields:
        if expected_length:
            arcpy.management.AddField(feature_class, field_name, expected_type, field_length=expected_length)
        else:
            arcpy.management.AddField(feature_class, field_name, expected_type)
        return

    field = fields[field_name]
    if not _field_requires_schema_fix(field, expected_type, expected_length):
        return

    temp_field = f"{field_name}_TMP"
    if temp_field in fields:
        arcpy.management.DeleteField(feature_class, [temp_field])

    if expected_length:
        arcpy.management.AddField(feature_class, temp_field, expected_type, field_length=expected_length)
    else:
        arcpy.management.AddField(feature_class, temp_field, expected_type)

    errors = []
    truncated_count = 0
    truncated_examples = []
    with arcpy.da.UpdateCursor(feature_class, ["OID@", field_name, temp_field]) as cursor:
        for row in cursor:
            oid = row[0]
            original_val = row[1]
            converted = None
            if not _is_missing_value(original_val):
                try:
                    converted = _convert_value_to_type(original_val, expected_type)
                    if expected_type == "TEXT" and expected_length is not None and converted is not None and len(converted) > expected_length:
                        if len(truncated_examples) < 3:
                            truncated_examples.append(f"OID {oid}: '{converted[:40]}'")
                        converted = converted[:expected_length]
                        truncated_count += 1
                except Exception:
                    if len(errors) < 3:
                        errors.append(f"OID {oid}: '{original_val}'")
            row[2] = converted
            cursor.updateRow(row)

    try:
        arcpy.management.DeleteField(feature_class, [field_name])
        if expected_length:
            arcpy.management.AddField(feature_class, field_name, expected_type, field_length=expected_length)
        else:
            arcpy.management.AddField(feature_class, field_name, expected_type)

        with arcpy.da.UpdateCursor(feature_class, [temp_field, field_name]) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)

        arcpy.management.DeleteField(feature_class, [temp_field])
    except Exception as e:
        log_message(f"Selhalo přejmenování pole {field_name}: {e}", "WARN")

    if errors:
        log_message(
            f"Konverze pole {field_name} na {expected_type}: některé hodnoty nešly převést. Příklady: {', '.join(errors)}",
            "CHECK"
        )

    if truncated_count > 0:
        log_message(
            f"Model {field_name}: zkraceno {truncated_count} textových hodnot na délku {expected_length}. Příklady: {', '.join(truncated_examples)}",
            "CHECK"
        )


def ensure_canonical_vr_fields(feature_class, target_attrs=None):
    """Naplní kanonická pole datového modelu GIS z CAD aliasů VR atributů."""
    if not feature_class or not arcpy.Exists(feature_class):
        return

    target_attrs = target_attrs or HEIGHT_ATTRIBUTES
    original_fields = [f.name for f in arcpy.ListFields(feature_class)]

    for target_attr in target_attrs:
        schema = FIELD_SCHEMA.get(target_attr)
        if not schema:
            continue

        expected_type, expected_length = schema
        source_fields = [
            field_name
            for field_name in _find_matching_source_fields(original_fields, target_attr)
            if field_name != target_attr
        ]

        _ensure_field_type(feature_class, target_attr, expected_type, expected_length)

        if not source_fields:
            continue

        with arcpy.da.UpdateCursor(feature_class, [target_attr] + source_fields) as cursor:
            for row in cursor:
                current_value = row[0]
                if not (_is_missing_value(current_value) or _is_zero_like_value(current_value)):
                    continue

                chosen_value = None
                for source_value in row[1:]:
                    if _is_missing_value(source_value):
                        continue
                    try:
                        converted_value = _convert_value_to_type(source_value, expected_type)
                    except Exception:
                        continue

                    if converted_value is None:
                        continue
                    if not _is_zero_like_value(converted_value):
                        chosen_value = converted_value
                        break
                    if chosen_value is None:
                        chosen_value = converted_value

                if chosen_value is not None:
                    row[0] = chosen_value
                    cursor.updateRow(row)

    ensure_npu_from_nup(feature_class)


def finalize_vyska_output_attributes(feature_class, layer_model_key, keep_prefixes=None):
    """Validace/finalizace atributů podle datového modelu pro výstupy Výšek."""
    if not feature_class or not arcpy.Exists(feature_class):
        return

    model = LAYER_MODEL_RULES.get(layer_model_key)
    if not model:
        log_message(f"Neznámý model vrstvy pro validaci: {layer_model_key}", "WARN")
        return

    keep_prefixes = keep_prefixes or []
    allowed_fields = list(model["allowed"])
    required_fields = set(model["required"])
    constants = model.get("constants", {})

    # 1) Alias NUP_MAX -> NPU_MAX
    if "NPU_MAX" in allowed_fields:
        ensure_npu_from_nup(feature_class)

    # 2) Schéma polí a případná konverze typů.
    for field_name in allowed_fields:
        schema = FIELD_SCHEMA.get(field_name)
        if not schema:
            continue
        expected_type, expected_length = schema
        _ensure_field_type(feature_class, field_name, expected_type, expected_length)
        ensure_field_domain(feature_class, field_name)

    # 3) Naplnění konstant a defaultů.
    edit_fields = []
    for k in constants:
        if k in [f.name for f in arcpy.ListFields(feature_class)]:
            edit_fields.append(k)
    if "ID_LOKAL" in [f.name for f in arcpy.ListFields(feature_class)] and "ID_LOKAL" not in edit_fields:
        edit_fields.append("ID_LOKAL")

    if edit_fields:
        with arcpy.da.UpdateCursor(feature_class, edit_fields) as cursor:
            for row in cursor:
                changed = False
                for idx, fname in enumerate(edit_fields):
                    if fname in constants:
                        const_value = constants[fname]
                        if _is_missing_value(row[idx]) or str(row[idx]) != str(const_value):
                            row[idx] = const_value
                            changed = True
                    elif fname == "ID_LOKAL":
                        if row[idx] is None:
                            row[idx] = 0
                            changed = True
                if changed:
                    cursor.updateRow(row)

    # 3b) Normalizace ID_LOKAL do rozsahu 1-999 (unikátně v rámci vrstvy).
    if "ID_LOKAL" in [f.name for f in arcpy.ListFields(feature_class)]:
        used_ids = set()
        invalid_oids = set()

        with arcpy.da.SearchCursor(feature_class, ["OID@", "ID_LOKAL"]) as cursor:
            for oid, id_val in cursor:
                try:
                    id_int = int(id_val)
                except Exception:
                    invalid_oids.add(oid)
                    continue

                if 1 <= id_int <= 999 and id_int not in used_ids:
                    used_ids.add(id_int)
                else:
                    invalid_oids.add(oid)

        if invalid_oids:
            available_ids = [i for i in range(1, 1000) if i not in used_ids]
            next_idx = 0
            overflow_count = 0

            with arcpy.da.UpdateCursor(feature_class, ["OID@", "ID_LOKAL"]) as cursor:
                for row in cursor:
                    oid = row[0]
                    if oid not in invalid_oids:
                        continue

                    if next_idx < len(available_ids):
                        row[1] = available_ids[next_idx]
                        next_idx += 1
                        cursor.updateRow(row)
                    else:
                        overflow_count += 1

            fixed_count = len(invalid_oids) - overflow_count
            if fixed_count > 0:
                log_message(
                    f"Validace {layer_model_key}: doplněno {fixed_count} hodnot ID_LOKAL do rozsahu 1-999",
                    "OK"
                )
            if overflow_count > 0:
                log_message(
                    f"Validace {layer_model_key}: nelze doplnit ID_LOKAL pro {overflow_count} prvků (vyčerpán rozsah 1-999)",
                    "CHECK"
                )

    # 3c) Pokud ve výškových polích není žádná smysluplná hodnota, vyčisti placeholderové nuly na NULL.
    _normalize_empty_height_placeholder_rows(feature_class)

    # 4) Kontrola required polí (non-nullable).
    for req in required_fields:
        if req not in [f.name for f in arcpy.ListFields(feature_class)]:
            log_message(f"Validace {layer_model_key}: chybí povinné pole {req}", "WARN")
            continue

        missing_count = 0
        with arcpy.da.SearchCursor(feature_class, [req]) as cursor:
            for row in cursor:
                if _is_missing_value(row[0]):
                    missing_count += 1
        if missing_count > 0:
            log_message(f"Validace {layer_model_key}: pole {req} má {missing_count} prázdných hodnot", "CHECK")

    # 5) Kontrola doménových hodnot.
    for domain_field, allowed_values in DOMAIN_ALLOWED_VALUES.items():
        if domain_field not in allowed_fields:
            continue
        if domain_field not in [f.name for f in arcpy.ListFields(feature_class)]:
            continue

        bad_count = 0
        bad_examples = []
        with arcpy.da.SearchCursor(feature_class, ["OID@", domain_field]) as cursor:
            for row in cursor:
                val = row[1]
                if _is_missing_value(val):
                    continue
                sval = str(val).strip().upper()
                if sval not in allowed_values:
                    bad_count += 1
                    if len(bad_examples) < 3:
                        bad_examples.append(f"OID {row[0]}: '{val}'")

        if bad_count > 0:
            log_message(
                f"Validace {layer_model_key}: pole {domain_field} má {bad_count} hodnot mimo doménu. Příklady: {', '.join(bad_examples)}",
                "CHECK"
            )

    # 5b) Rozsah ID_LOKAL dle modelu (1-999).
    if "ID_LOKAL" in allowed_fields and "ID_LOKAL" in [f.name for f in arcpy.ListFields(feature_class)]:
        out_of_range = 0
        out_examples = []
        with arcpy.da.SearchCursor(feature_class, ["OID@", "ID_LOKAL"]) as cursor:
            for row in cursor:
                val = row[1]
                if val is None:
                    continue
                try:
                    ival = int(val)
                except Exception:
                    out_of_range += 1
                    if len(out_examples) < 3:
                        out_examples.append(f"OID {row[0]}: '{val}'")
                    continue

                if ival < 1 or ival > 999:
                    out_of_range += 1
                    if len(out_examples) < 3:
                        out_examples.append(f"OID {row[0]}: '{val}'")

        if out_of_range > 0:
            log_message(
                f"Validace {layer_model_key}: ID_LOKAL mimo rozsah 1-999 u {out_of_range} prvků. Příklady: {', '.join(out_examples)}",
                "CHECK"
            )

    # 6) Ořez nepovolených polí.
    allowed_set = set(allowed_fields)
    fields_to_delete = []
    for field in arcpy.ListFields(feature_class):
        name = field.name
        if name in allowed_set:
            continue
        if any(name.startswith(prefix) for prefix in keep_prefixes):
            continue
        if field.required or field.type in ("OID", "Geometry"):
            continue
        if name.lower() in ("shape_length", "shape_area"):
            continue
        fields_to_delete.append(name)

    if fields_to_delete:
        arcpy.management.DeleteField(feature_class, fields_to_delete)

    # 7) Převod prázdných řetězců na NULL u textových polí (VYSKA_VB_I a jiná nepovinná pole).
    text_fields_to_clean = [
        f.name for f in arcpy.ListFields(feature_class)
        if f.type == "String" and f.name in allowed_set and f.name not in constants
    ]
    if text_fields_to_clean:
        with arcpy.da.UpdateCursor(feature_class, text_fields_to_clean) as cursor:
            for row in cursor:
                changed = False
                for i, val in enumerate(row):
                    if isinstance(val, str) and val.strip() == "":
                        row[i] = None
                        changed = True
                if changed:
                    cursor.updateRow(row)


def get_model_height_attributes(fields):
    """Vrátí pouze výškové atributy datového modelu, které jsou dostupné v daném seznamu polí."""
    if not fields:
        return []
    field_set = set(fields)
    return [attr for attr in HEIGHT_ATTRIBUTES if attr in field_set]


def get_vr_attributes(vr_feature_class):
    """
    Získá POUZE relevantní atributy z VR bloků (výškové + dokumentační)
    Vyloučí CAD metadata (Entity, Handle, Layer, Color atd.)
    Returns: seznam názvů atributů
    """
    # Systémová pole
    excluded_fields = {
        "OBJECTID", "SHAPE", "SHAPE_LENGTH", "SHAPE_AREA", 
        "FID", "OID", "GLOBALID", "TARGET_FID", "SC_TYPE",
        "JOIN_FID", "JOIN_COUNT"
    }
    
    # CAD metadata - vyloučit (každý blok má unikátní hodnoty)
    cad_metadata_prefixes = {
        "ENTITY", "HANDLE", "LAYER", "LYR", "COLOR", "LINETYPE", 
        "LTSCALE", "ELEVATION", "THICKNESS", "LINEWT", "BLK",
        "ENT", "EXT", "DOC", "REF", "GLOBALWIDTH"
    }
    
    vr_attrs = []
    try:
        all_field_names = [field.name for field in arcpy.ListFields(vr_feature_class)]
        matched_height_fields = set()
        for attr in HEIGHT_ATTRIBUTES:
            matched_height_fields.update(_find_matching_source_fields(all_field_names, attr))

        for field in arcpy.ListFields(vr_feature_class):
            field_upper = field.name.upper()
            
            # Skip systémová pole
            if field_upper in excluded_fields:
                continue
            if field_upper.startswith("SHAPE"):
                continue
            if field.type in ["Geometry", "OID"]:
                continue

            if field.name in matched_height_fields:
                vr_attrs.append(field.name)
                continue
            
            # Skip CAD metadata
            is_cad_metadata = False
            for prefix in cad_metadata_prefixes:
                if field_upper.startswith(prefix):
                    is_cad_metadata = True
                    break
            
            if not is_cad_metadata:
                vr_attrs.append(field.name)
    except:
        pass
    
    return vr_attrs


def transfer_joined_attributes(feature_class, attrs_to_fix):
    """Po SpatialJoin přenese hodnoty z polí typu ATTR_1/ATTR_12 do cílových ATTR polí."""
    if not feature_class or not arcpy.Exists(feature_class) or not attrs_to_fix:
        return

    sj_fields = [f.name for f in arcpy.ListFields(feature_class)]
    for attr in attrs_to_fix:
        source_fields = [field_name for field_name in _find_matching_source_fields(sj_fields, attr) if field_name != attr]
        if not source_fields:
            continue

        if attr not in sj_fields:
            schema = FIELD_SCHEMA.get(attr)
            if not schema:
                continue
            expected_type, expected_length = schema
            _ensure_field_type(feature_class, attr, expected_type, expected_length)
            sj_fields = [f.name for f in arcpy.ListFields(feature_class)]
        elif attr in FIELD_SCHEMA:
            expected_type, expected_length = FIELD_SCHEMA[attr]
            _ensure_field_type(feature_class, attr, expected_type, expected_length)

        if attr in sj_fields:
            read_fields = [attr] + source_fields
            with arcpy.da.UpdateCursor(feature_class, read_fields) as cursor:
                for row in cursor:
                    current_value = row[0]
                    if not (_is_missing_value(current_value) or _is_zero_like_value(current_value)):
                        continue

                    chosen = None
                    # Preferuj nenull a nenulové hodnoty.
                    for src_value in row[1:]:
                        if _is_missing_value(src_value):
                            continue
                        if attr in FIELD_SCHEMA:
                            expected_type, _ = FIELD_SCHEMA[attr]
                            try:
                                src_value = _convert_value_to_type(src_value, expected_type)
                            except Exception:
                                continue

                        if src_value is None:
                            continue
                        if not _is_zero_like_value(src_value):
                            chosen = src_value
                            break
                        if chosen is None:
                            chosen = src_value

                    if chosen is not None:
                        row[0] = chosen
                        cursor.updateRow(row)


def ensure_npu_from_nup(feature_class):
    """Zajistí naplnění NPU_MAX z NUP_MAX (CAD alias), pokud je NPU_MAX prázdné."""
    if not feature_class or not arcpy.Exists(feature_class):
        return

    fields = [f.name for f in arcpy.ListFields(feature_class)]
    if "NUP_MAX" not in fields:
        return

    if "NPU_MAX" not in fields:
        arcpy.management.AddField(feature_class, "NPU_MAX", "SHORT")

    def _is_missing(value):
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    def _is_zero_like(value):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return value == 0
        if isinstance(value, str):
            txt = value.strip().replace(",", ".")
            if txt == "":
                return False
            try:
                return float(txt) == 0.0
            except Exception:
                return False
        return False

    with arcpy.da.UpdateCursor(feature_class, ["NPU_MAX", "NUP_MAX"]) as cursor:
        for row in cursor:
            if _is_missing(row[1]):
                continue
            if _is_missing(row[0]) or (_is_zero_like(row[0]) and not _is_zero_like(row[1])):
                row[0] = row[1]
                cursor.updateRow(row)


def propagate_best_values_by_target(feature_class, attrs, target_field="TARGET_FID"):
    """Pro každý TARGET_FID vybere nejplnější sadu atributů a doplní ji do ostatních řádků."""
    if not feature_class or not arcpy.Exists(feature_class) or not attrs:
        return

    fields = [f.name for f in arcpy.ListFields(feature_class)]
    if target_field not in fields:
        return

    attrs_present = [a for a in attrs if a in fields]
    if not attrs_present:
        return

    cursor_fields = [target_field] + attrs_present

    def _is_missing(value):
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    def _is_zero_like(value):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return value == 0
        if isinstance(value, str):
            txt = value.strip().replace(",", ".")
            if txt == "":
                return False
            try:
                return float(txt) == 0.0
            except Exception:
                return False
        return False

    def _value_score(value):
        if _is_missing(value):
            return -1
        if _is_zero_like(value):
            return 0
        return 1

    # Najdi nejlepší hodnotu pro každý atribut a TARGET_FID zvlášť.
    best_by_target = {}
    with arcpy.da.SearchCursor(feature_class, cursor_fields) as cursor:
        for row in cursor:
            target_id = row[0]
            values = list(row[1:])

            if target_id not in best_by_target:
                best_by_target[target_id] = {
                    "scores": [-2] * len(attrs_present),
                    "values": [None] * len(attrs_present),
                }

            for idx, val in enumerate(values):
                score = _value_score(val)
                if score > best_by_target[target_id]["scores"][idx]:
                    best_by_target[target_id]["scores"][idx] = score
                    best_by_target[target_id]["values"][idx] = val

    # Doplň chybějící/placeholder hodnoty z nejlepšího záznamu stejného TARGET_FID.
    with arcpy.da.UpdateCursor(feature_class, cursor_fields) as cursor:
        for row in cursor:
            target_id = row[0]
            best = best_by_target.get(target_id)
            if not best:
                continue

            best_vals = best["values"]
            changed = False
            for idx in range(len(attrs_present)):
                current_val = row[idx + 1]
                donor_val = best_vals[idx]

                if _is_missing(donor_val):
                    continue

                if _is_missing(current_val):
                    row[idx + 1] = donor_val
                    changed = True
                elif _is_zero_like(current_val) and not _is_zero_like(donor_val):
                    row[idx + 1] = donor_val
                    changed = True

            if changed:
                cursor.updateRow(row)


def _ensure_field_from_template(feature_class, field_name, template_field):
    existing_fields = [f.name for f in arcpy.ListFields(feature_class)]
    if field_name in existing_fields:
        return

    if field_name in FIELD_SCHEMA:
        expected_type, expected_length = FIELD_SCHEMA[field_name]
        _ensure_field_type(feature_class, field_name, expected_type, expected_length)
        return

    field_type_map = {
        "String": "TEXT",
        "SmallInteger": "SHORT",
        "Integer": "LONG",
        "Long": "LONG",
        "Single": "FLOAT",
        "Double": "DOUBLE",
        "Date": "DATE",
    }
    resolved_type = field_type_map.get(template_field.type, "TEXT")

    if resolved_type == "TEXT":
        field_length = getattr(template_field, "length", None) or 255
        arcpy.management.AddField(feature_class, field_name, resolved_type, field_length=field_length)
    else:
        arcpy.management.AddField(feature_class, field_name, resolved_type)


def _has_meaningful_assignment(values):
    for value in values:
        if _is_missing_value(value):
            continue
        if _is_zero_like_value(value):
            continue
        return True
    return False


def _normalize_empty_height_placeholder_rows(feature_class, height_fields=None):
    """Vyčistí placeholderové nuly v řádcích, kde ve skutečnosti chybí výšková regulace."""
    if not feature_class or not arcpy.Exists(feature_class):
        return

    fields = [f.name for f in arcpy.ListFields(feature_class)]
    height_fields = [field_name for field_name in (height_fields or HEIGHT_ATTRIBUTES) if field_name in fields]
    if not height_fields:
        return

    with arcpy.da.UpdateCursor(feature_class, height_fields) as cursor:
        for row in cursor:
            values = list(row)
            if _has_meaningful_assignment(values):
                continue

            changed = False
            for idx, value in enumerate(values):
                if _is_missing_value(value):
                    continue
                row[idx] = None
                changed = True

            if changed:
                cursor.updateRow(row)


def _has_usable_geometry(geometry):
    if geometry is None:
        return False
    try:
        if getattr(geometry, "isEmpty", False):
            return False
    except Exception:
        pass

    try:
        return geometry.firstPoint is not None or geometry.lastPoint is not None
    except Exception:
        return False


def build_unique_line_block_assignment(target_lines_fc, join_features_fc, out_feature_class, attrs_to_fix,
                                       tolerance_meters=NOCAD_VR_ASSIGN_TOLERANCE_METERS,
                                       log_label="NOCAD"):
    """Přiřadí atributy jen tam, kde existuje skutečně unikátní vazba linie ↔ VR blok v toleranci."""
    if not target_lines_fc or not arcpy.Exists(target_lines_fc):
        return None

    if arcpy.Exists(out_feature_class):
        arcpy.management.Delete(out_feature_class)
    arcpy.conversion.ExportFeatures(target_lines_fc, out_feature_class)

    total_lines = get_feature_count(out_feature_class)
    if not join_features_fc or not arcpy.Exists(join_features_fc):
        log_message(f"{log_label}: VR bloky nejsou k dispozici, ponechávám {total_lines} linií bez výškových atributů.", "INFO")
        return out_feature_class

    candidate_fc = r"memory\vr_unique_candidates"
    if arcpy.Exists(candidate_fc):
        arcpy.management.Delete(candidate_fc)

    arcpy.analysis.SpatialJoin(
        target_features=out_feature_class,
        join_features=join_features_fc,
        out_feature_class=candidate_fc,
        join_operation="JOIN_ONE_TO_MANY",
        join_type="KEEP_ALL",
        match_option="WITHIN_A_DISTANCE",
        search_radius=f"{tolerance_meters} Meters"
    )

    transfer_joined_attributes(candidate_fc, attrs_to_fix)
    ensure_npu_from_nup(candidate_fc)
    propagate_best_values_by_target(candidate_fc, attrs_to_fix)
    ensure_npu_from_nup(candidate_fc)

    candidate_fields = {f.name: f for f in arcpy.ListFields(candidate_fc)}
    if "TARGET_FID" not in candidate_fields or "JOIN_FID" not in candidate_fields:
        log_message(f"{log_label}: chybí TARGET_FID/JOIN_FID po SpatialJoin, ponechávám linie bez přiřazení.", "WARN")
        return out_feature_class

    attrs_present = [attr for attr in attrs_to_fix if attr in candidate_fields]
    assignment_attrs = [attr for attr in HEIGHT_ATTRIBUTES if attr in attrs_present] or attrs_present
    for attr in attrs_present:
        _ensure_field_from_template(out_feature_class, attr, candidate_fields[attr])

    pair_values = {}
    target_to_join = {}
    join_to_target = {}

    with arcpy.da.SearchCursor(candidate_fc, ["TARGET_FID", "JOIN_FID"] + attrs_present) as cursor:
        for row in cursor:
            target_fid = row[0]
            join_fid = row[1]

            try:
                join_fid = int(join_fid)
            except Exception:
                continue

            if join_fid < 0:
                continue

            values = list(row[2:])
            assignment_values = [values[attrs_present.index(attr)] for attr in assignment_attrs]
            if not _has_meaningful_assignment(assignment_values):
                continue

            target_to_join.setdefault(target_fid, set()).add(join_fid)
            join_to_target.setdefault(join_fid, set()).add(target_fid)

            pair_key = (target_fid, join_fid)
            if pair_key not in pair_values:
                pair_values[pair_key] = values
            else:
                merged = list(pair_values[pair_key])
                for idx, value in enumerate(values):
                    current_value = merged[idx]
                    if _is_missing_value(current_value):
                        merged[idx] = value
                    elif _is_zero_like_value(current_value) and not _is_zero_like_value(value):
                        merged[idx] = value
                pair_values[pair_key] = merged

    shared_join_ids = {
        join_fid for join_fid, target_ids in join_to_target.items()
        if len(target_ids) != 1
    }

    unique_assignment = {}
    ambiguous_target_ids = set()
    shared_target_ids = set()

    for target_fid, join_ids in target_to_join.items():
        if len(join_ids) != 1:
            ambiguous_target_ids.add(target_fid)
            continue

        join_fid = next(iter(join_ids))
        if join_fid in shared_join_ids:
            shared_target_ids.add(target_fid)
            continue

        unique_assignment[target_fid] = pair_values.get((target_fid, join_fid), [])

    if attrs_present and unique_assignment:
        with arcpy.da.UpdateCursor(out_feature_class, ["OID@"] + attrs_present) as cursor:
            for row in cursor:
                target_oid = row[0]
                assigned_values = unique_assignment.get(target_oid)
                if not assigned_values:
                    continue

                changed = False
                for idx, value in enumerate(assigned_values):
                    attr_name = attrs_present[idx]
                    if _is_missing_value(value):
                        continue
                    if attr_name in HEIGHT_ATTRIBUTES and _is_zero_like_value(value):
                        continue

                    current_value = row[idx + 1]
                    if _is_missing_value(current_value):
                        row[idx + 1] = value
                        changed = True
                    elif _is_zero_like_value(current_value) and not _is_zero_like_value(value):
                        row[idx + 1] = value
                        changed = True

                if changed:
                    cursor.updateRow(row)

    matched_target_ids = set(target_to_join.keys())
    without_candidate_count = max(total_lines - len(matched_target_ids), 0)
    ambiguous_line_count = len(ambiguous_target_ids | shared_target_ids)
    assigned_count = len(unique_assignment)

    log_message(
        f"{log_label}: unikátně přiřazeno {assigned_count} liniím, bez kandidáta {without_candidate_count}, "
        f"nejednoznačných linií {ambiguous_line_count} (tolerance {tolerance_meters:.2f} m).",
        "INFO"
    )

    return out_feature_class


class Toolbox(object):
    def __init__(self):
        self.label = "MADASPRU CAD Import - Výšky v2"
        self.alias = "MADASPRU_Vysky_v2"
        self.tools = [HeightRegulationImport]


class HeightRegulationImport(object):
    def __init__(self):
        self.label = "Import CAD vrstev (Výšky)"
        self.alias = "heightRegulationImport"
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
            try:
                default_path = r"C:\GIS_Data\Output.gdb"
                if arcpy.Exists(default_path):
                    param2.value = default_path
            except:
                pass

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

        # Search radius pro split
        param9 = arcpy.Parameter(
            displayName="Search Radius pro Split (m)",
            name="split_radius",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param9.value = 0.001

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and parameters[0].value:
            cad_file = parameters[0].valueAsText
            original_workspace = arcpy.env.workspace
            
            try:
                # Uživatel může omylem zadat složku místo konkrétního CAD souboru.
                resolved_cad_file = cad_file
                if os.path.isdir(cad_file):
                    cad_candidates = []
                    for file_name in os.listdir(cad_file):
                        if file_name.lower().endswith((".dwg", ".dxf", ".dgn")):
                            cad_candidates.append(os.path.join(cad_file, file_name))
                    if cad_candidates:
                        resolved_cad_file = cad_candidates[0]
                        arcpy.AddWarning(f"Input je složka, používám CAD soubor: {os.path.basename(resolved_cad_file)}")

                arcpy.env.workspace = resolved_cad_file
                available_layers = []
                all_polyline_layers = []

                polyline_fc = None
                if arcpy.Exists("Polyline"):
                    polyline_fc = "Polyline"
                elif arcpy.Exists(os.path.join(resolved_cad_file, "Polyline")):
                    polyline_fc = os.path.join(resolved_cad_file, "Polyline")

                if polyline_fc:
                    with arcpy.da.SearchCursor(polyline_fc, ["Layer"]) as cursor:
                        all_polyline_layers = sorted(set([row[0] for row in cursor if row[0]]))

                    for layer in all_polyline_layers:
                        # SC vrstvy + VR vrstvy
                        if layer.startswith("3011") and "_PL_SC_" in layer:
                            available_layers.append(f"{layer} (Polyline)")
                        elif layer in DEFAULT_LAYERS:
                            available_layers.append(f"{layer} (Polyline)")

                    # Fallback: pokud žádná vrstva nesedí na očekávaný pattern, nabídneme všechny polyline vrstvy.
                    if not available_layers and all_polyline_layers:
                        available_layers = [f"{layer} (Polyline)" for layer in all_polyline_layers]
                        arcpy.AddWarning("Nenalezeny očekávané názvy vrstev 3011/302xxx, zobrazuji všechny Polyline vrstvy z CAD.")
                else:
                    arcpy.AddWarning("V CAD souboru nebyla nalezena feature class 'Polyline'.")
                
                parameters[1].filter.list = available_layers
                parameters[1].values = available_layers
                parameters[1].enabled = len(available_layers) > 0
                
                if not parameters[6].altered:
                    parameters[6].value = arcpy.SpatialReference(5514)
                    
            except Exception as e:
                arcpy.AddWarning(f"Chyba při načítání CAD: {e}")
            finally:
                arcpy.env.workspace = original_workspace

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True
        
        # ============================================================
        # FÁZE 0: NAČTENÍ PARAMETRŮ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 0: NAČTENÍ PARAMETRŮ", "STEP")
        log_message("=" * 60, "INFO")
        
        input_cad = parameters[0].valueAsText
        selected_layers = parameters[1].values if parameters[1].values else []
        output_gdb = parameters[2].valueAsText
        
        fd_name = parameters[3].valueAsText
        xy_tolerance = parameters[4].value or 0.01
        xy_resolution = parameters[5].value or 0.001
        output_sr = parameters[6].value or arcpy.SpatialReference(5514)
        transform_method = parameters[7].valueAsText
        out_prefix = parameters[8].valueAsText or ""
        split_radius = parameters[9].value or 0.001
        
        log_message(f"CAD soubor: {input_cad}", "INFO")
        log_message(f"Output GDB: {output_gdb}", "INFO")
        log_message(f"Split radius: {split_radius}m", "INFO")
        log_message(f"Vybraných vrstev: {len(selected_layers)}", "INFO")

        # Vytvoření Feature Dataset pokud je zadán
        if fd_name:
            fd_path = os.path.join(output_gdb, fd_name)
            if not arcpy.Exists(fd_path):
                log_message(f"Vytvářím Feature Dataset: {fd_name}", "STEP")
                arcpy.CreateFeatureDataset_management(
                    out_dataset_path=output_gdb,
                    out_name=fd_name,
                    spatial_reference=output_sr
                )
                arcpy.env.XYTolerance = f"{xy_tolerance} Meters"
                arcpy.env.XYResolution = f"{xy_resolution} Meters"
            output_workspace = fd_path
        else:
            output_workspace = output_gdb

        # ============================================================
        # FÁZE 1: IMPORT A PŘÍPRAVA DAT
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 1: IMPORT A PŘÍPRAVA DAT", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_layers = []  # Seznam SC vrstev pro merge
        vr_rozhrani_layer = None  # 302211 - rozhraní
        vr_na_linii_layer = None  # 302210 - VR bloky na linii
        vr_na_bod_layer = None  # 302110 - VR bloky na bod
        exported_count = 0
        
        for layer_info in selected_layers:
            if " (Polyline)" in layer_info:
                layer_name = layer_info.replace(" (Polyline)", "")
                
                arcpy.env.workspace = input_cad
                
                field_delimited = arcpy.AddFieldDelimiters("Polyline", "Layer")
                where_clause = f"{field_delimited} = '{layer_name}'"
                
                if out_prefix:
                    base_name = f"{out_prefix}{layer_name}_LN"
                else:
                    base_name = f"PL_{layer_name}_LN"
                
                output_name = generate_unique_name(output_gdb, base_name)
                output_fc = os.path.join(output_workspace, output_name)
                
                try:
                    arcpy.FeatureClassToFeatureClass_conversion(
                        in_features="Polyline",
                        out_path=output_workspace,
                        out_name=output_name,
                        where_clause=where_clause
                    )
                    
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
                        arcpy.DefineProjection_management(output_fc, output_sr)
                    
                    count = get_feature_count(output_fc)
                    log_message(f"Importováno: {layer_name} ({count} prvků)", "OK")
                    exported_count += 1
                    
                    # Kategorizace vrstev
                    if layer_name.startswith("3011") and "_PL_SC_" in layer_name:
                        sc_layers.append(output_fc)
                    elif layer_name == "302211_PL_VR_na_linii_rozhrani":
                        vr_rozhrani_layer = output_fc
                    elif layer_name == "302110_BL_VR_na_bod":
                        vr_na_bod_layer = output_fc
                    elif layer_name == "302210_BL_VR_na_linii":
                        vr_na_linii_layer = output_fc
                    
                except Exception as e:
                    log_message(f"Chyba při exportu {layer_name}: {e}", "ERROR")

        log_message(f"Celkem importováno: {exported_count} vrstev", "OK")
        log_message(f"SC vrstev: {len(sc_layers)}", "DEBUG")
        log_message(f"VR rozhraní: {'Ano' if vr_rozhrani_layer else 'Ne'}", "DEBUG")
        log_message(f"VR na linii: {'Ano' if vr_na_linii_layer else 'Ne'}", "DEBUG")

        # Uložit mapování: layer_path -> type_name pro identifikaci po merge
        sc_type_mapping = {}  # {layer_path: type_name}
        for sc_layer in sc_layers:
            layer_basename = os.path.basename(sc_layer)
            # Extrahuj typ ze jména (např. "PL_301110_PL_SC_uzavrena_LN" -> "301110_PL_SC_uzavrena")
            if out_prefix:
                type_name = layer_basename.replace(out_prefix, "").replace("_LN", "")
            else:
                type_name = layer_basename.replace("PL_", "", 1).replace("_LN", "")
            sc_type_mapping[sc_layer] = type_name
            log_message(f"SC vrstva registrována: {type_name}", "DEBUG")

        # Merge SC vrstev + přidání pole SC_TYPE (aby bylo možné rozdělit zpět)
        merged_sc_all = None
        if len(sc_layers) >= 1:
            try:
                merged_sc_all = r"memory\sc_all_merged"
                
                # Přidat pole SC_TYPE do každé SC vrstvy PŘED mergem
                for sc_layer in sc_layers:
                    sc_type = sc_type_mapping[sc_layer]
                    
                    # Přidat pole pokud neexistuje
                    existing_fields = [f.name for f in arcpy.ListFields(sc_layer)]
                    if "SC_TYPE" not in existing_fields:
                        arcpy.management.AddField(sc_layer, "SC_TYPE", "TEXT", field_length=100)
                        log_message(f"Přidáno pole SC_TYPE do {os.path.basename(sc_layer)}", "DEBUG")
                    
                    # Nastavit hodnotu
                    updated_count = 0
                    with arcpy.da.UpdateCursor(sc_layer, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            row[0] = sc_type
                            cursor.updateRow(row)
                            updated_count += 1
                    log_message(f"SC_TYPE='{sc_type}' nastaveno pro {updated_count} prvků", "DEBUG")
                
                # Merge
                if len(sc_layers) >= 2:
                    arcpy.Merge_management(sc_layers, merged_sc_all)
                    log_message(f"Sloučeno {len(sc_layers)} SC vrstev (s polem SC_TYPE)", "OK")
                else:
                    arcpy.CopyFeatures_management(sc_layers[0], merged_sc_all)
                    log_message(f"Zkopírována 1 SC vrstva (s polem SC_TYPE)", "OK")
                
                sc_count = get_feature_count(merged_sc_all)
                log_message(f"Celkem SC linií: {sc_count}", "DEBUG")
                
                # DEBUG - kontrola SC_TYPE po merge
                fields = [f.name for f in arcpy.ListFields(merged_sc_all)]
                if "SC_TYPE" in fields:
                    sc_types_found = set()
                    with arcpy.da.SearchCursor(merged_sc_all, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            if row[0]:
                                sc_types_found.add(row[0])
                    log_message(f"SC_TYPE po merge: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
                else:
                    log_message("CHYBA: SC_TYPE pole CHYBÍ po merge!", "ERROR")
                
            except Exception as e:
                log_message(f"Chyba při merge SC vrstev: {e}", "ERROR")
                return

        # Zpracování VR bloků na linii - MultipartToSinglepart a filtrování kruhů
        vr_circles = None
        vr_join_points = None
        vr_join_features = None
        if vr_na_linii_layer and arcpy.Exists(vr_na_linii_layer):
            try:
                log_message("Zpracovávám VR bloky na linii...", "STEP")
                
                # Singlepart
                singlepart_temp = r"memory\vr_linii_singlepart"
                arcpy.management.MultipartToSinglepart(vr_na_linii_layer, singlepart_temp)
                
                # Filtrování uzavřených linií (kruhy)
                if out_prefix:
                    circles_name = f"{out_prefix}302210_VR_circles"
                else:
                    circles_name = "PL_302210_BL_VR_na_linii_circles"
                
                circles_name = generate_unique_name(output_gdb, circles_name)
                vr_circles = os.path.join(output_workspace, circles_name)
                
                arcpy.management.CreateFeatureclass(
                    out_path=output_workspace,
                    out_name=circles_name,
                    geometry_type="POLYLINE",
                    template=singlepart_temp,
                    spatial_reference=output_sr
                )
                
                field_names = [field.name for field in arcpy.ListFields(singlepart_temp) 
                              if field.type != "OID" and field.name.upper() != "OBJECTID"]
                
                circles_count = 0
                with arcpy.da.SearchCursor(singlepart_temp, ["SHAPE@"] + field_names) as search_cursor:
                    with arcpy.da.InsertCursor(vr_circles, ["SHAPE@"] + field_names) as insert_cursor:
                        for row in search_cursor:
                            geometry = row[0]
                            if geometry and geometry.firstPoint.X == geometry.lastPoint.X and geometry.firstPoint.Y == geometry.lastPoint.Y:
                                insert_cursor.insertRow(row)
                                circles_count += 1
                
                ensure_canonical_vr_fields(vr_circles)

                log_message(f"Nalezeno {circles_count} VR bloků (uzavřených linií/kruhů)", "OK")
                
                arcpy.Delete_management(singlepart_temp)
                arcpy.Delete_management(vr_na_linii_layer)
                
            except Exception as e:
                log_message(f"Chyba při zpracování VR bloků: {e}", "ERROR")

        # Připrav body (centroidy) pro join atributů z VR bloků na linie.
        # Body snapujeme na hranu SC, aby join fungoval i při drobném posunu bloků.
        if vr_circles and merged_sc_all and arcpy.Exists(vr_circles) and arcpy.Exists(merged_sc_all):
            try:
                arcpy.management.FeatureToPoint(
                    in_features=vr_circles,
                    out_feature_class=r"memory\vr_join_points",
                    point_location="CENTROID"
                )

                snap_env = [[merged_sc_all, "EDGE", "0.3 Meters"]]
                arcpy.edit.Snap(r"memory\vr_join_points", snap_env)

                vr_join_points = r"memory\vr_join_points"
                vr_join_features = vr_join_points
                log_message(f"Připraveno {get_feature_count(vr_join_points)} centroidů VR bloků pro join", "DEBUG")
            except Exception as e:
                log_message(f"Nelze připravit centroidy VR bloků pro join, použiji kruhy: {e}", "WARN")
                vr_join_features = vr_circles
        else:
            vr_join_features = vr_circles

        # ============================================================
        # FÁZE 2: VYTVOŘENÍ BODŮ ROZHRANÍ Z CAD
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 2: VYTVOŘENÍ BODŮ ROZHRANÍ Z CAD", "STEP")
        log_message("=" * 60, "INFO")
        
        rozhrani_body = None
        rozhrani_count_cad = 0
        vr_block_split_points = None
        vr_block_split_count = 0
        
        if vr_rozhrani_layer and merged_sc_all and arcpy.Exists(vr_rozhrani_layer) and arcpy.Exists(merged_sc_all):
            try:
                # Intersect rozhraní se SC liniemi → body
                log_message("Hledám průsečíky rozhraní se SC liniemi...", "STEP")
                
                # Nejdřív SNAP rozhraní na SC linie (0.5m edge)
                rozhrani_for_intersect = vr_rozhrani_layer
                try:
                    log_message("Snap bodů rozhraní ke SC liniím (0.5m edge)...", "STEP")
                    # Export do memory pro editaci
                    rozhrani_snap_tm = r"memory\rozhrani_lines_snap"
                    arcpy.conversion.ExportFeatures(vr_rozhrani_layer, rozhrani_snap_tm)
                    
                    # Snap 
                    snap_env = [[merged_sc_all, "EDGE", "0.5 Meters"]]
                    arcpy.edit.Snap(rozhrani_snap_tm, snap_env)
                    
                    rozhrani_for_intersect = rozhrani_snap_tm
                    log_message("Snap rozhraní dokončen", "DEBUG")
                except Exception as e:
                    log_message(f"Snap rozhraní selhal, použiji původní: {e}", "WARN")

                arcpy.analysis.PairwiseIntersect(
                    in_features=[rozhrani_for_intersect, merged_sc_all],
                    out_feature_class=r"memory\rozhrani_body_multipart",
                    join_attributes="NO_FID",
                    cluster_tolerance="0.05 Meters",
                    output_type="POINT"
                )
                
                # Multipart to Singlepart
                arcpy.management.MultipartToSinglepart(
                    in_features=r"memory\rozhrani_body_multipart",
                    out_feature_class=r"memory\rozhrani_body_cad"
                )

                # Doplňkový zdroj bodů: konce rozhraní linií snapnuté na SC.
                # PairwiseIntersect může minout T-junction nebo kollineární kontakt.
                # Konce rozhraní linií jsou přesně tam, kde kreslíř zamýšlel řez.
                try:
                    arcpy.management.FeatureVerticesToPoints(
                        in_features=rozhrani_for_intersect,
                        out_feature_class=r"memory\rozhrani_endpoints",
                        point_location="BOTH_ENDS"
                    )
                    # Snap na SC edge (max 0.5m)
                    arcpy.edit.Snap(r"memory\rozhrani_endpoints", [[merged_sc_all, "EDGE", "0.5 Meters"]])
                    # Zachovat jen ty, které leží na SC (do 0.05m)
                    arcpy.management.MakeFeatureLayer(r"memory\rozhrani_endpoints", "rozhrani_ep_lyr")
                    arcpy.management.SelectLayerByLocation(
                        in_layer="rozhrani_ep_lyr",
                        overlap_type="INTERSECT",
                        select_features=merged_sc_all,
                        search_distance="0.05 Meters",
                        selection_type="NEW_SELECTION"
                    )
                    ep_on_sc = int(arcpy.GetCount_management("rozhrani_ep_lyr")[0])
                    if ep_on_sc > 0:
                        arcpy.management.Append(
                            inputs="rozhrani_ep_lyr",
                            target=r"memory\rozhrani_body_cad",
                            schema_type="NO_TEST"
                        )
                        log_message(f"Doplněno {ep_on_sc} split bodů z konců rozhraní linií", "DEBUG")
                    arcpy.management.Delete("rozhrani_ep_lyr")
                    arcpy.management.Delete(r"memory\rozhrani_endpoints")
                except Exception as ep_err:
                    log_message(f"Doplňkové endpoint body selhaly (nevadí): {ep_err}", "DEBUG")

                # Deduplikace bodů (sjetí na stejné místo po merge)
                try:
                    arcpy.management.DeleteIdentical(r"memory\rozhrani_body_cad", ["Shape"], "0.02 Meters")
                except Exception:
                    pass

                rozhrani_body = r"memory\rozhrani_body_cad"
                rozhrani_count_cad = get_feature_count(rozhrani_body)
                
                log_message(f"Nalezeno {rozhrani_count_cad} bodů rozhraní z CAD", "OK")
                
                # Snap bodů rozhraní ke SC liniím (30cm edge snap)
                log_message("Snap bodů rozhraní ke SC liniím (30cm edge)...", "STEP")
                try:
                    # Snap settings: [[snap_environment, snap_type, distance]]
                    snap_env = [[merged_sc_all, "EDGE", "0.3 Meters"]]
                    arcpy.edit.Snap(rozhrani_body, snap_env)
                    log_message("Snap dokončen", "OK")
                except Exception as snap_error:
                    log_message(f"Snap selhal (pokračuji bez snap): {snap_error}", "WARN")
                
                arcpy.Delete_management(r"memory\rozhrani_body_multipart")
                
            except Exception as e:
                log_message(f"Chyba při vytváření bodů rozhraní: {e}", "ERROR")
        else:
            log_message("VR rozhraní vrstva nebyla nalezena - přeskakuji", "WARN")

        has_cad_rozhrani = bool(
            rozhrani_body and arcpy.Exists(rozhrani_body) and rozhrani_count_cad > 0
        )

        # Hybridní režim: v jednom CAD mohou být současně části s CAD rozhraními i bez nich.
        sc_cad_scope = merged_sc_all
        sc_nocad_scope = None
        sc_cad_scope_count = get_feature_count(merged_sc_all) if merged_sc_all else 0
        sc_nocad_scope_count = 0
        has_cad_processing_scope = has_cad_rozhrani

        if has_cad_rozhrani and merged_sc_all and arcpy.Exists(merged_sc_all):
            try:
                arcpy.management.MakeFeatureLayer(merged_sc_all, "sc_scope_lyr")

                # 1) Seed: linie, které přímo leží na CAD rozhraních.
                arcpy.management.SelectLayerByLocation(
                    in_layer="sc_scope_lyr",
                    overlap_type="INTERSECT",
                    select_features=rozhrani_body,
                    search_distance="0.35 Meters",
                    selection_type="NEW_SELECTION",
                    invert_spatial_relationship="NOT_INVERT"
                )

                seed_count = int(arcpy.GetCount_management("sc_scope_lyr")[0])
                if seed_count > 0:
                    arcpy.conversion.ExportFeatures("sc_scope_lyr", r"memory\sc_cad_scope_seed")

                    # 2) Expanze na souvislé komponenty linií (bloky), aby CAD větev
                    # zahrnovala celé bloky s rozhraními, ne jen linie s přímým průsečíkem.
                    scope_expand_fc = r"memory\sc_cad_scope_seed"
                    prev_count = -1
                    for _ in range(50):
                        arcpy.management.MakeFeatureLayer(merged_sc_all, "sc_scope_expand_lyr")
                        arcpy.management.SelectLayerByLocation(
                            in_layer="sc_scope_expand_lyr",
                            overlap_type="INTERSECT",
                            select_features=scope_expand_fc,
                            search_distance="0.02 Meters",
                            selection_type="NEW_SELECTION",
                            invert_spatial_relationship="NOT_INVERT"
                        )

                        expanded_count = int(arcpy.GetCount_management("sc_scope_expand_lyr")[0])
                        arcpy.conversion.ExportFeatures("sc_scope_expand_lyr", r"memory\sc_cad_scope_expand")
                        arcpy.management.Delete("sc_scope_expand_lyr")

                        scope_expand_fc = r"memory\sc_cad_scope_expand"
                        if expanded_count == prev_count:
                            break
                        prev_count = expanded_count

                    if arcpy.Exists(r"memory\sc_cad_scope_expand"):
                        sc_cad_scope = r"memory\sc_cad_scope_expand"
                        sc_cad_scope_count = get_feature_count(sc_cad_scope)
                    else:
                        sc_cad_scope = r"memory\sc_cad_scope_seed"
                        sc_cad_scope_count = seed_count
                else:
                    sc_cad_scope = None
                    sc_cad_scope_count = 0

                # 3) NOCAD scope je doplněk k CAD scope.
                arcpy.management.SelectLayerByLocation(
                    in_layer="sc_scope_lyr",
                    overlap_type="INTERSECT",
                    select_features=sc_cad_scope if sc_cad_scope else rozhrani_body,
                    search_distance="0.02 Meters",
                    selection_type="NEW_SELECTION",
                    invert_spatial_relationship="INVERT"
                )

                sc_nocad_scope_count = int(arcpy.GetCount_management("sc_scope_lyr")[0])
                if sc_nocad_scope_count > 0:
                    arcpy.conversion.ExportFeatures("sc_scope_lyr", r"memory\sc_nocad_scope")
                    sc_nocad_scope = r"memory\sc_nocad_scope"

                arcpy.management.Delete("sc_scope_lyr")

                has_cad_processing_scope = sc_cad_scope_count > 0
                log_message(
                    f"Hybrid režim: CAD větev {sc_cad_scope_count} linií (seed {seed_count}), bez CAD rozhraní {sc_nocad_scope_count} linií",
                    "INFO"
                )
            except Exception as scope_error:
                log_message(f"Rozdělení CAD/NOCAD scope selhalo, použiji jednotný režim: {scope_error}", "WARN")
                sc_cad_scope = merged_sc_all
                sc_nocad_scope = None
                sc_cad_scope_count = get_feature_count(merged_sc_all)
                sc_nocad_scope_count = 0
                has_cad_processing_scope = has_cad_rozhrani

        if not has_cad_processing_scope:
            if sc_nocad_scope and arcpy.Exists(sc_nocad_scope):
                sc_cad_scope = sc_nocad_scope
            elif not sc_cad_scope and merged_sc_all and arcpy.Exists(merged_sc_all):
                sc_cad_scope = merged_sc_all

        # V CAD větvi držíme minimálně 30 cm toleranci řezu (osvědčené chování původního workflow).
        try:
            cad_split_radius = max(float(split_radius), 0.3)
        except Exception:
            cad_split_radius = 0.3

        if not has_cad_processing_scope:
            log_message("CAD rozhraní nejsou k dispozici pro žádnou část SC - zachovám původní SC linie bez splitu podle dynamických VR bloků.", "INFO")

        # Doplňkové split body z VR bloků jsou vypnuté.
        # CAD větev řežeme výhradně podle rozhraní (CAD + dogenerovaná),
        # NOCAD větev se neřeže.
        if has_cad_processing_scope:
            log_message("Doplňkové split body z VR bloků jsou vypnuté (CAD větev používá jen rozhraní).", "INFO")
        else:
            log_message("Bez CAD rozhraní negeneruji doplňkové split body z VR bloků.", "INFO")

        # ============================================================
        # FÁZE 3: PRVNÍ ŘEZÁNÍ SC PODLE CAD ROZHRANÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 3: PRVNÍ ŘEZÁNÍ SC PODLE CAD ROZHRANÍ", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_split_cad = None
        split_points_for_phase3 = None
        split_points_count = 0

        if has_cad_processing_scope:
            if rozhrani_body and rozhrani_count_cad > 0:
                split_points_for_phase3 = rozhrani_body
                split_points_count = rozhrani_count_cad

        if split_points_for_phase3 and split_points_count > 0:
            try:
                log_message(f"Řežu SC linie v {split_points_count} místech rozhraní...", "STEP")
                
                arcpy.management.SplitLineAtPoint(
                    in_features=sc_cad_scope,
                    point_features=split_points_for_phase3,
                    out_feature_class=r"memory\sc_split_cad",
                    search_radius=f"{cad_split_radius} Meters"
                )
                
                sc_split_cad = r"memory\sc_split_cad"
                split_count = get_feature_count(sc_split_cad)
                
                log_message(f"SC rozděleny na {split_count} segmentů", "OK")
                
            except Exception as e:
                log_message(f"Chyba při řezání SC: {e}", "ERROR")
                sc_split_cad = sc_cad_scope  # Fallback na původní
        else:
            if has_cad_processing_scope:
                log_message("Žádná CAD rozhraní - SC zůstávají nerozdělené", "WARN")
            else:
                log_message("Bez CAD rozhraní přeskakuji split podle VR bloků - SC zůstávají v původní geometrii", "INFO")
            sc_split_cad = sc_cad_scope

        # ============================================================
        # FÁZE 4: PŘIPOJENÍ VR BLOKŮ K SEGMENTŮM
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 4: PŘIPOJENÍ VR BLOKŮ K SEGMENTŮM", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_with_vr = None
        
        if vr_join_features and sc_split_cad and arcpy.Exists(vr_join_features):
            try:
                log_message("Připojuji VR bloky k SC segmentům (SpatialJoin přes centroidy)...", "STEP")
                
                arcpy.analysis.SpatialJoin(
                    target_features=sc_split_cad,
                    join_features=vr_join_features,
                    out_feature_class=r"memory\sc_with_vr",
                    join_operation="JOIN_ONE_TO_MANY",
                    join_type="KEEP_ALL",
                    match_option="INTERSECT",
                    search_radius=None
                )
                
                sc_with_vr = r"memory\sc_with_vr"
                joined_count = get_feature_count(sc_with_vr)
                
                log_message(f"Spatial join dokončen: {joined_count} záznamů", "OK")
                
                # Debug - kolik má připojené VR
                with arcpy.da.SearchCursor(sc_with_vr, ["Join_Count"]) as cursor:
                    with_vr = sum(1 for row in cursor if row[0] and row[0] > 0)
                log_message(f"Segmentů s připojeným VR blokem: {with_vr}", "DEBUG")
                
            except Exception as e:
                log_message(f"Chyba při SpatialJoin: {e}", "ERROR")
                sc_with_vr = sc_split_cad
        else:
            log_message("VR bloky nebyly nalezeny - pokračuji bez připojení výšek", "WARN")
            sc_with_vr = sc_split_cad

        # ============================================================
        # FÁZE 5: DOGENEROVÁNÍ CHYBĚJÍCÍCH ROZHRANÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 5: DOGENEROVÁNÍ CHYBĚJÍCÍCH ROZHRANÍ", "STEP")
        log_message("=" * 60, "INFO")
        
        rozhrani_body_all = rozhrani_body  # Začneme s CAD rozhraními
        rozhrani_all = rozhrani_body  # Alias pro FÁZE 8
        
        if has_cad_processing_scope and sc_with_vr and vr_circles:
            try:
                # Dynamicky získej VŠECHNY atributy z VR bloků
                vr_attributes = get_vr_attributes(vr_circles)
                log_message(f"VR atributy z bloků: {', '.join(vr_attributes) if vr_attributes else 'žádné'}", "DEBUG")
                
                # Zjisti, které z VR atributů jsou dostupné v sc_with_vr
                available_height_attrs = []
                fields = [f.name for f in arcpy.ListFields(sc_with_vr)]
                for attr in vr_attributes:
                    if attr in fields:
                        available_height_attrs.append(attr)
                
                log_message(f"Dostupné výškové atributy v SC: {', '.join(available_height_attrs)}", "DEBUG")
                
                if available_height_attrs:
                    # Dissolve podle atributů datového modelu výšek.
                    log_message("Dissolve podle výškových atributů datového modelu...", "STEP")
                    
                    # Vytvoř statistiky UNIQUE pro každý atribut
                    stats_fields = ";".join([f"{attr} UNIQUE" for attr in available_height_attrs])
                    
                    arcpy.management.Dissolve(
                        in_features=sc_with_vr,
                        out_feature_class=r"memory\sc_dissolve",
                        dissolve_field=available_height_attrs,
                        statistics_fields=stats_fields,
                        multi_part="SINGLE_PART",
                        unsplit_lines="DISSOLVE_LINES"
                    )
                    
                    dissolve_count = get_feature_count(r"memory\sc_dissolve")
                    log_message(f"Po dissolve: {dissolve_count} spojených segmentů", "DEBUG")
                    
                    # Vyber pouze ty s určenou výškou (alespoň jeden atribut není NULL)
                    where_parts = []
                    for attr in available_height_attrs:
                        where_parts.append(f"{attr} IS NOT NULL")
                    where_clause = " OR ".join(where_parts)
                    
                    arcpy.management.MakeFeatureLayer(r"memory\sc_dissolve", "sc_dissolve_lyr")

                    arcpy.management.SelectLayerByAttribute(
                        in_layer_or_view="sc_dissolve_lyr",
                        selection_type="NEW_SELECTION",
                        where_clause=where_clause
                    )
                    
                    selected_count = int(arcpy.GetCount_management("sc_dissolve_lyr")[0])
                    log_message(f"Segmentů s výškou: {selected_count}", "DEBUG")
                    
                    if selected_count > 0:
                        # Koncové body těchto segmentů
                        arcpy.management.FeatureVerticesToPoints(
                            in_features="sc_dissolve_lyr",
                            out_feature_class=r"memory\dissolve_vertices",
                            point_location="BOTH_ENDS"
                        )
                        
                        vertices_count = get_feature_count(r"memory\dissolve_vertices")
                        log_message(f"Koncových bodů: {vertices_count}", "DEBUG")
                        
                        # Najdi body které se překrývají (= rozhraní mezi různými typy)
                        arcpy.analysis.Intersect(
                            in_features=r"memory\dissolve_vertices",
                            out_feature_class=r"memory\overlapping_points",
                            join_attributes="ONLY_FID",
                            output_type="POINT"
                        )
                        
                        overlap_count = get_feature_count(r"memory\overlapping_points")
                        log_message(f"Překrývajících se bodů: {overlap_count}", "DEBUG")
                        
                        if overlap_count > 0:
                            # Dissolve překrývajících bodů do jednoho
                            arcpy.management.Dissolve(
                                in_features=r"memory\overlapping_points",
                                out_feature_class=r"memory\generated_rozhrani",
                                dissolve_field=None,
                                multi_part="SINGLE_PART"
                            )
                            
                            generated_count = get_feature_count(r"memory\generated_rozhrani")
                            log_message(f"Dogenerováno {generated_count} chybějících rozhraní", "OK")

                            # Export dogenerovaných rozhraní pro kontrolu
                            # Snap dogenerovaných rozhraní ke SC liniím
                            if sc_cad_scope and arcpy.Exists(sc_cad_scope):
                                log_message("Snap dogenerovaných rozhraní ke SC liniím (30cm edge)...", "STEP")
                                try:
                                    snap_env = [[sc_cad_scope, "EDGE", "0.3 Meters"]]
                                    arcpy.edit.Snap(r"memory\generated_rozhrani", snap_env)
                                    log_message("Snap dokončen", "OK")
                                except Exception as snap_error:
                                    log_message(f"Snap selhal (pokračuji bez snap): {snap_error}", "WARN")
                            
                            # Merge CAD rozhraní + vygenerovaná
                            if rozhrani_body and arcpy.Exists(rozhrani_body):
                                arcpy.management.Merge(
                                    inputs=[rozhrani_body, r"memory\generated_rozhrani"],
                                    output=r"memory\rozhrani_all"
                                )
                            else:
                                arcpy.CopyFeatures_management(
                                    r"memory\generated_rozhrani",
                                    r"memory\rozhrani_all"
                                )
                            
                            rozhrani_body_all = r"memory\rozhrani_all"
                            rozhrani_all = rozhrani_body_all  # Alias pro FÁZE 8
                            total_rozhrani = get_feature_count(rozhrani_body_all)
                            log_message(f"Celkem rozhraní: {total_rozhrani}", "OK")
                            
                            # Cleanup
                            arcpy.Delete_management(r"memory\overlapping_points")
                            arcpy.Delete_management(r"memory\generated_rozhrani")
                        else:
                            log_message("Žádná dodatečná rozhraní nebyla potřeba", "INFO")
                        
                        arcpy.Delete_management(r"memory\dissolve_vertices")
                    
                    # Clear selection
                    arcpy.management.SelectLayerByAttribute(
                        in_layer_or_view="sc_dissolve_lyr",
                        selection_type="CLEAR_SELECTION"
                    )
                    arcpy.management.Delete("sc_dissolve_lyr")
                    arcpy.Delete_management(r"memory\sc_dissolve")
                    
                else:
                    log_message("Žádné výškové atributy nebyly nalezeny", "WARN")
                    
            except Exception as e:
                log_message(f"Chyba při generování rozhraní: {e}", "ERROR")
        elif not has_cad_processing_scope:
            log_message("FÁZE 5 přeskočena: bez CAD rozhraní negeneruji dodatečná rozhraní ani mezilehlé dissolve.", "INFO")

        # ============================================================
        # FÁZE 6: FINÁLNÍ ŘEZÁNÍ VŠEMI ROZHRANÍMI
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 6: FINÁLNÍ ŘEZÁNÍ VŠEMI ROZHRANÍMI", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_final_split = None

        if not has_cad_processing_scope:
            sc_final_split = sc_split_cad
            final_count = get_feature_count(sc_final_split)
            log_message("Bez CAD rozhraní přeskakuji finální dissolve/split a zachovávám původní segmentaci linií.", "INFO")
            log_message(f"Finální počet segmentů bez CAD rozhraní: {final_count}", "OK")
        else:
            try:
                # Dissolve původních SC (čistá geometrie) - ZACHOVAT SC_TYPE
                log_message("Dissolve původních SC linií...", "STEP")
                
                arcpy.management.Dissolve(
                    in_features=sc_cad_scope,
                    out_feature_class=r"memory\sc_dissolve_clean",
                    dissolve_field="SC_TYPE",  # Zachovat typ SC
                    multi_part="SINGLE_PART",
                    unsplit_lines="DISSOLVE_LINES" 
                )
                
                clean_count = get_feature_count(r"memory\sc_dissolve_clean")
                log_message(f"Čistých spojených SC: {clean_count}", "DEBUG")
                
                # DEBUG - kontrola SC_TYPE po dissolve
                fields = [f.name for f in arcpy.ListFields(r"memory\sc_dissolve_clean")]
                if "SC_TYPE" in fields:
                    sc_types_found = set()
                    with arcpy.da.SearchCursor(r"memory\sc_dissolve_clean", ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            if row[0]:
                                sc_types_found.add(row[0])
                    log_message(f"SC_TYPE po dissolve: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
                else:
                    log_message("VAROVÁNÍ: SC_TYPE pole CHYBÍ po dissolve!", "WARN")
                
                # Finální split všemi rozhraními
                split_points_for_phase6 = None
                split_points_count_phase6 = 0

                if rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
                    split_points_for_phase6 = rozhrani_body_all
                    split_points_count_phase6 = get_feature_count(rozhrani_body_all)

                if split_points_for_phase6 and split_points_count_phase6 > 0:
                    log_message(f"Řežu SC linie v {split_points_count_phase6} místech rozhraní...", "STEP")
                    
                    arcpy.management.SplitLineAtPoint(
                        in_features=r"memory\sc_dissolve_clean",
                        point_features=split_points_for_phase6,
                        out_feature_class=r"memory\sc_final_split",
                        search_radius=f"{cad_split_radius} Meters"
                    )
                    
                    sc_final_split = r"memory\sc_final_split"
                else:
                    log_message("Žádná rozhraní ani VR split body - používám dissolve výstup", "WARN")
                    sc_final_split = r"memory\sc_dissolve_clean"
                
                final_count = get_feature_count(sc_final_split)
                log_message(f"Finální počet segmentů po split: {final_count}", "OK")
                
                # DEBUG - kontrola SC_TYPE po split
                fields = [f.name for f in arcpy.ListFields(sc_final_split)]
                if "SC_TYPE" in fields:
                    sc_types_found = set()
                    with arcpy.da.SearchCursor(sc_final_split, ["SC_TYPE"]) as cursor:
                        for row in cursor:
                            if row[0]:
                                sc_types_found.add(row[0])
                    log_message(f"SC_TYPE po split: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
                else:
                    log_message("VAROVÁNÍ: SC_TYPE pole CHYBÍ po split!", "WARN")
                
            except Exception as e:
                log_message(f"Chyba při finálním split: {e}", "ERROR")
                sc_final_split = sc_cad_scope

        # ============================================================
        # FÁZE 7: ČIŠTĚNÍ FALEŠNÝCH ROZHRANÍ (podle notebooku)
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 7: ČIŠTĚNÍ FALEŠNÝCH ROZHRANÍ", "STEP")
        log_message("=" * 60, "INFO")
        
        # Logika z notebooku:
        # 1. Najdi koncové body SC segmentů
        # 2. Vyber ty, které NEKOLIDUJÍ s rozhraními (falešné řezy)
        # 3. Spoj segmenty, které mají tyto falešné řezy
        
        sc_cleaned = sc_final_split
        cleanup_boundary_points = None

        if has_cad_processing_scope and rozhrani_body_all and arcpy.Exists(rozhrani_body_all):
            cleanup_boundary_points = rozhrani_body_all
        
        try:
            if cleanup_boundary_points and arcpy.Exists(cleanup_boundary_points):
                log_message("Detekuji falešná rozhraní (koncové body mimo skutečná rozhraní)...", "STEP")
                
                # 1. Extrahuj všechny koncové body SC segmentů
                arcpy.management.FeatureVerticesToPoints(
                    in_features=sc_final_split,
                    out_feature_class=r"memory\sc_split_endpoints",
                    point_location="BOTH_ENDS"
                )
                
                endpoints_count = get_feature_count(r"memory\sc_split_endpoints")
                log_message(f"Nalezeno {endpoints_count} koncových bodů", "DEBUG")
                
                # 2. Vyber body, které NEKOLIDUJÍ s rozhraními (= falešné řezy)
                arcpy.management.MakeFeatureLayer(r"memory\sc_split_endpoints", "endpoints_lyr")
                
                arcpy.management.SelectLayerByLocation(
                    in_layer="endpoints_lyr",
                    overlap_type="INTERSECT",
                    select_features=cleanup_boundary_points,
                    search_distance="0.35 Meters",  # Trochu větší než split radius
                    selection_type="NEW_SELECTION",
                    invert_spatial_relationship="INVERT"
                )
                
                false_endpoints_count = int(arcpy.GetCount_management("endpoints_lyr")[0])
                log_message(f"Falešných koncových bodů (mimo rozhraní): {false_endpoints_count}", "DEBUG")
                
                if false_endpoints_count > 0:
                    arcpy.conversion.ExportFeatures(
                        in_features="endpoints_lyr",
                        out_features=r"memory\false_endpoints"
                    )
                    
                    # Export falešných bodů pro kontrolu - DISABLED FOR FINAL CLEANUP
                    # try:
                    #     if out_prefix:
                    #         false_name = f"{out_prefix}Rozhrani_falesne"
                    #     else:
                    #         false_name = "Z_Rozhrani_falesne"
                    #     
                    #     false_name = generate_unique_name(output_gdb, false_name)
                    #     false_output = os.path.join(output_workspace, false_name)
                    #     
                    #     arcpy.CopyFeatures_management(r"memory\false_endpoints", false_output)
                    #     log_message(f"Export falešných rozhraní (merged back): {false_name}", "DEBUG")
                    # except Exception as e:
                    #     log_message(f"Chyba při exportu falešných rozhraní: {e}", "WARN")

                    
                    # 3. Vyber SC segmenty, které se dotýkají falešných bodů
                    arcpy.management.MakeFeatureLayer(sc_final_split, "sc_split_lyr")
                    
                    arcpy.management.SelectLayerByLocation(
                        in_layer="sc_split_lyr",
                        overlap_type="INTERSECT",
                        select_features=r"memory\false_endpoints",
                        search_distance=None,
                        selection_type="NEW_SELECTION",
                        invert_spatial_relationship="NOT_INVERT"
                    )
                    
                    segments_to_merge = int(arcpy.GetCount_management("sc_split_lyr")[0])
                    log_message(f"Segmentů s falešnými rozhraními: {segments_to_merge}", "DEBUG")
                    
                    if segments_to_merge > 0:
                        # 4. Spoj tyto segmenty (dissolve podle SC_TYPE - aby se nespojily různé typy)
                        arcpy.conversion.ExportFeatures(
                            in_features="sc_split_lyr",
                            out_features=r"memory\segments_to_merge"
                        )
                        
                        # Dissolve podle SC_TYPE a ORIG_FID, aby se nespojovaly různé
                        # části jedné čáry přes hranice s odlišnými VR bloky.
                        seg_fields = [f.name for f in arcpy.ListFields(r"memory\segments_to_merge")]
                        dissolve_fields = []
                        if "SC_TYPE" in seg_fields:
                            dissolve_fields.append("SC_TYPE")
                        if "ORIG_FID" in seg_fields:
                            dissolve_fields.append("ORIG_FID")
                        
                        arcpy.management.Dissolve(
                            in_features=r"memory\segments_to_merge",
                            out_feature_class=r"memory\segments_merged",
                            dissolve_field=dissolve_fields,
                            statistics_fields=None,
                            multi_part="SINGLE_PART",
                            unsplit_lines="DISSOLVE_LINES"
                        )
                        
                        merged_count = get_feature_count(r"memory\segments_merged")
                        log_message(f"Po spojení falešných řezů: {merged_count} segmentů", "DEBUG")
                        
                        # 5. Najdi původní segmenty, které leží WITHIN spojených (= budou smazány)
                        arcpy.management.SelectLayerByLocation(
                            in_layer="sc_split_lyr",
                            overlap_type="WITHIN",
                            select_features=r"memory\segments_merged",
                            search_distance=None,
                            selection_type="NEW_SELECTION",
                            invert_spatial_relationship="NOT_INVERT"
                        )
                        
                        segments_to_delete = int(arcpy.GetCount_management("sc_split_lyr")[0])
                        log_message(f"Mazání {segments_to_delete} původních segmentů...", "DEBUG")
                        
                        # 6. Smazání původních rozdělených segmentů
                        if segments_to_delete > 0:
                            arcpy.management.DeleteRows("sc_split_lyr")
                        
                        # 7. Merge spojených segmentů zpět do sc_final_split
                        arcpy.management.Append(
                            inputs=r"memory\segments_merged",
                            target=sc_final_split,
                            schema_type="NO_TEST"
                        )
                        
                        final_cleaned_count = get_feature_count(sc_final_split)
                        log_message(f"Po čištění falešných rozhraní: {final_cleaned_count} segmentů", "OK")
                        log_message(f"Odstraněno {segments_to_delete - merged_count} falešných řezů", "OK")
                    else:
                        log_message("Žádné segmenty s falešnými rozhraními nenalezeny", "DEBUG")
                else:
                    log_message("Všechny koncové body odpovídají skutečným rozhraním", "OK")
                
                sc_cleaned = sc_final_split
                
            else:
                log_message("Žádná rozhraní - přeskakuji čištění", "DEBUG")
                sc_cleaned = sc_final_split
        
        except Exception as e:
            log_message(f"Chyba při čištění falešných rozhraní: {e}", "WARN")
            log_message("Pokračuji s nečištěnými segmenty", "WARN")
            sc_cleaned = sc_final_split
        
        # DEBUG - kontrola SC_TYPE
        fields = [f.name for f in arcpy.ListFields(sc_cleaned)]
        if "SC_TYPE" in fields:
            sc_types_found = set()
            with arcpy.da.SearchCursor(sc_cleaned, ["SC_TYPE"]) as cursor:
                for row in cursor:
                    if row[0]:
                        sc_types_found.add(row[0])
            log_message(f"SC_TYPE zachováno: {len(sc_types_found)} typů", "DEBUG")

        # Překopírování sc_cleaned do čerstvého memory feature class.
        # Po operacích DeleteRows + Append v Phase 7 může být prostorový index
        # in-memory feature class neplatný, což způsobuje 0 shod v Phase 8 SpatialJoin.
        try:
            arcpy.conversion.ExportFeatures(sc_cleaned, r"memory\sc_cleaned_fresh")
            sc_cleaned = r"memory\sc_cleaned_fresh"
        except Exception as _refresh_err:
            log_message(f"Nepodařilo se obnovit sc_cleaned (pokračuji s původním): {_refresh_err}", "WARN")

        # ============================================================
        # FÁZE 8: FINÁLNÍ PŘIPOJENÍ ATRIBUTŮ (podle notebooku)
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 8: FINÁLNÍ PŘIPOJENÍ ATRIBUTŮ", "STEP")
        log_message("=" * 60, "INFO")
        
        sc_final_with_vr = None
        sc_final_with_vr_cad = None
        sc_final_with_vr_nocad = None
        
        if vr_join_features and arcpy.Exists(vr_join_features) and sc_cleaned:
            try:
                # Finální SpatialJoin s VR bloky (podle notebooku)
                log_message("Finální SpatialJoin s VR bloky...", "STEP")

                attrs_to_fix = [
                    "OZNACENI", "NAZEV_BLOK", "DRUH_UP", "DRUH_INFO",
                    "NP_MIN", "NP_MAX", "NPU_MAX", "NUP_MAX",
                    "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX",
                    "VYSKA_VB", "VYSKA_VB_I", "DOK_NAZEV"
                ]

                # Centroidy VR bloků byly snapnuty na merged_sc_all před Phase 6 Dissolve.
                # Dissolve může souřadnice vrcholů zaokrouhlit na grid (XY resolution),
                # takže centroidy po dissolve neleží přesně na liniích sc_cleaned.
                # Přesnapujeme kopii centroidů na sc_cleaned (0.1m tolerance = 100× větší
                # než typická grid odchylka; bezpečné pokud jsou SC linie > 20 cm od sebe).
                vr_join_for_sj = vr_join_features
                try:
                    arcpy.conversion.ExportFeatures(vr_join_features, r"memory\vr_join_phase8")
                    arcpy.edit.Snap(r"memory\vr_join_phase8", [[sc_cleaned, "EDGE", "0.1 Meters"]])
                    vr_join_for_sj = r"memory\vr_join_phase8"
                    snapped_count = int(arcpy.GetCount_management(vr_join_for_sj)[0])
                    log_message(f"Centroidy přesnapovány na sc_cleaned: {snapped_count} bodů", "DEBUG")
                except Exception as _snap_err:
                    log_message(f"Přesnap centroidů selhal, použiji originál: {_snap_err}", "WARN")
                    vr_join_for_sj = vr_join_features

                if has_cad_processing_scope:
                    vr_join_for_cad = vr_join_for_sj
                    try:
                        arcpy.management.MakeFeatureLayer(vr_join_for_sj, "vr_phase8_cad_lyr")
                        arcpy.management.SelectLayerByLocation(
                            in_layer="vr_phase8_cad_lyr",
                            overlap_type="WITHIN_A_DISTANCE",
                            select_features=sc_cleaned,
                            search_distance=f"{cad_split_radius} Meters",
                            selection_type="NEW_SELECTION",
                            invert_spatial_relationship="NOT_INVERT"
                        )
                        cad_seed_count = int(arcpy.GetCount_management("vr_phase8_cad_lyr")[0])
                        log_message(f"VR bloků relevantních pro CAD větev: {cad_seed_count}", "DEBUG")
                        if cad_seed_count > 0:
                            arcpy.conversion.ExportFeatures("vr_phase8_cad_lyr", r"memory\vr_join_phase8_cad")
                            vr_join_for_cad = r"memory\vr_join_phase8_cad"
                    except Exception as _cad_scope_err:
                        log_message(f"Filtrace VR bloků pro CAD větev selhala, použiji všechny: {_cad_scope_err}", "WARN")
                        vr_join_for_cad = vr_join_for_sj
                    finally:
                        if arcpy.Exists("vr_phase8_cad_lyr"):
                            arcpy.management.Delete("vr_phase8_cad_lyr")

                    arcpy.analysis.SpatialJoin(
                        target_features=sc_cleaned,
                        join_features=vr_join_for_cad,
                        out_feature_class=r"memory\sc_final_sj",
                        join_operation="JOIN_ONE_TO_MANY",
                        join_type="KEEP_ALL",
                        match_option="WITHIN_A_DISTANCE",
                        search_radius=f"{cad_split_radius} Meters"
                    )

                    transfer_joined_attributes(r"memory\sc_final_sj", attrs_to_fix)
                    ensure_npu_from_nup(r"memory\sc_final_sj")
                    propagate_best_values_by_target(r"memory\sc_final_sj", attrs_to_fix)
                    ensure_npu_from_nup(r"memory\sc_final_sj")
                else:
                    log_message(
                        f"Bez CAD rozhraní páruji linie jen s unikátním VR blokem do {NOCAD_VR_ASSIGN_TOLERANCE_METERS:.2f} m.",
                        "INFO"
                    )
                    build_unique_line_block_assignment(
                        sc_cleaned,
                        vr_join_for_sj,
                        r"memory\sc_final_sj",
                        attrs_to_fix,
                        tolerance_meters=NOCAD_VR_ASSIGN_TOLERANCE_METERS,
                        log_label="NOCAD hlavní větev"
                    )
                
                sj_count = get_feature_count(r"memory\sc_final_sj")
                log_message(f"SpatialJoin výsledek: {sj_count} záznamů", "DEBUG")
                
                # DEBUG - kontrola SC_TYPE po SpatialJoin
                fields_sj = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                if "SC_TYPE" in fields_sj:
                    log_message("SC_TYPE nalezeno po SpatialJoin", "DEBUG")
                else:
                    log_message("VAROVÁNÍ: SC_TYPE CHYBÍ po SpatialJoin!", "WARN")

                if has_cad_processing_scope and "Join_Count" in fields_sj:
                    with arcpy.da.SearchCursor(r"memory\sc_final_sj", ["Join_Count"]) as cursor:
                        seeded_count = sum(1 for row in cursor if row[0] and row[0] > 0)
                    log_message(f"Segmentů se seed atributy po finálním CAD joinu: {seeded_count}", "DEBUG")

                # Diagnostika: které modelové výškové atributy nejsou ve zdroji VR dostupné.
                missing_model_attrs = []
                for attr in HEIGHT_ATTRIBUTES:
                    if attr == "NPU_MAX":
                        if "NPU_MAX" in fields_sj or "NUP_MAX" in fields_sj or any(f.startswith("NUP_MAX_") for f in fields_sj):
                            continue
                    if attr in fields_sj or any(f.startswith(f"{attr}_") for f in fields_sj):
                        continue
                    missing_model_attrs.append(attr)
                if missing_model_attrs:
                    log_message(
                        f"VR bloky neobsahují atributy {', '.join(missing_model_attrs)} - ve výstupu zůstanou NULL.",
                        "INFO"
                    )
                
                # ============================================================
                # PROPAGACE ATRIBUTŮ MEZI ROZHRANÍMI
                # ============================================================
                # ============================================================
                # PROPAGACE ATRIBUTŮ (SERIAL & PARALLEL)
                # ============================================================
                # Cíl: Přenést atributy přes rozdělené segmenty (i různých typů),
                # POKUD mezi nimi není rozhraní.
                
                log_message("Spouštím chytrou propagaci atributů (Respektuje rozhraní)...", "STEP")
                
                if vr_circles and arcpy.Exists(vr_circles):
                    vr_attributes = get_vr_attributes(vr_circles)
                else:
                    vr_attributes = []
                
                fields = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                available_height_attrs = [attr for attr in vr_attributes if attr in fields]
                has_cad_barriers = bool(rozhrani_body and arcpy.Exists(rozhrani_body) and get_feature_count(rozhrani_body) > 0)
                do_propagation = has_cad_barriers
                
                if available_height_attrs:
                    if not do_propagation:
                        log_message("CAD rozhraní nejsou k dispozici - propagace vypnuta, zachovávám 1:1 připojení z VR bloků.", "INFO")

                    # 1. Vytvoř buffer kolem rozhraní (to jsou bariéry)
                    # Používáme POUZE rozhrani_body (z CADu), nikoliv rozhrani_body_all (které obsahuje i dogenerované)
                    # Chceme, aby se atributy přelily přes dogenerovaná rozhraní (která vznikla jen proto, že tam chyběla data),
                    # ale aby se zastavily o skutečná CAD rozhraní.
                    
                    barrier_geom = None
                    if do_propagation:
                        barrier_source = None
                        
                        if rozhrani_body and arcpy.Exists(rozhrani_body):
                            barrier_source = rozhrani_body
                        elif vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
                             # Fallback na linie, kdyby body nebyly (nemělo by nastat)
                            barrier_source = vr_rozhrani_layer
                        
                        if barrier_source:
                            try:
                                # Tolerance 2cm (trochu víc než snap 1cm)
                                arcpy.analysis.Buffer(barrier_source, r"memory\rozhrani_buffer", "0.02 Meters")
                                # Načti VŠECHNY buffery jako seznam geometrií pro správnou detekci bariér
                                if int(arcpy.GetCount_management(r"memory\rozhrani_buffer")[0]) > 0:
                                    barrier_geom = [
                                        row[0]
                                        for row in arcpy.da.SearchCursor(r"memory\rozhrani_buffer", ["SHAPE@"])
                                        if _has_usable_geometry(row[0])
                                    ]
                            except Exception as e:
                                log_message(f"Nepodařilo se vytvořit bariéry pro propagaci: {e}", "WARN")
                                barrier_geom = None

                    # 2. Načti segmenty
                    # OID -> {geom, attrs, has_data, orig_fid, sc_type}
                    segments_data = {}
                    
                    # Zkontrolujeme pole
                    fields_in_sc = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                    
                    has_orig_fid_field = "ORIG_FID" in fields_in_sc
                    has_sc_type_field = "SC_TYPE" in fields_in_sc
                    
                    cursor_fields = ["OBJECTID", "SHAPE@"] + available_height_attrs
                    if has_orig_fid_field: cursor_fields.append("ORIG_FID")
                    if has_sc_type_field: cursor_fields.append("SC_TYPE")
                    
                    with arcpy.da.SearchCursor(r"memory\sc_final_sj", cursor_fields) as cursor:
                        for row in cursor:
                            oid = row[0]
                            geom = row[1]
                            attr_len = len(available_height_attrs)
                            attrs = list(row[2:2+attr_len])
                            
                            # Parsuj extra fieldy
                            current_idx = 2 + attr_len
                            
                            orig_fid = -1
                            if has_orig_fid_field:
                                orig_fid = row[current_idx]
                                current_idx += 1
                                
                            sc_type = None
                            if has_sc_type_field:
                                raw_type = row[current_idx]
                                if raw_type:
                                    sc_type = str(raw_type).strip().lower() # Normalizace pro porovnání
                                else:
                                    sc_type = None
                                current_idx += 1
                            
                            # Determine has_data, strictly excluding ORIG_FID or generic fields
                            # attrs list corresponds to available_height_attrs
                            meaningful_attrs = []
                            for idx, attr_val in enumerate(attrs):
                                field_name = available_height_attrs[idx]
                                # Ignorujeme technická pole pro určení, zda má segment "data" k propagaci
                                if "ORIG_FID" in field_name or "SC_TYPE" in field_name or "TARGET_FID" in field_name:
                                    continue
                                meaningful_attrs.append(attr_val)
                            has_real_data = _has_meaningful_assignment(meaningful_attrs)
                            
                            segments_data[oid] = {
                                "geom": geom, 
                                "attrs": attrs, 
                                "has_data": has_real_data, 
                                "orig_fid": orig_fid,
                                "sc_type": sc_type
                            }

                    # 3. Iterativní propagace
                    if do_propagation:
                        max_iterations = 10
                        
                        for i in range(max_iterations):
                            updates = {} # oid -> new_attrs
                            
                            # Projdi jen ty bez dat
                            null_segments = {k: v for k, v in segments_data.items() if not v["has_data"]}
                            filled_segments = {k: v for k, v in segments_data.items() if v["has_data"]}
                            
                            if not null_segments:
                                break
                                
                            log_message(f"Iterace {i+1}: Segmentů bez dat: {len(null_segments)}, s daty: {len(filled_segments)}", "DEBUG")

                            # Pro každý prázdný segment
                            for null_oid, null_info in null_segments.items():
                                null_geom = null_info["geom"]
                                null_fid = null_info["orig_fid"]
                                null_type = null_info["sc_type"]

                                if not _has_usable_geometry(null_geom):
                                    continue
                                
                                # Najdi souseda s daty
                                candidate_attrs = None
                                
                                for fill_oid, fill_info in filled_segments.items():
                                    fill_geom = fill_info["geom"]
                                    fill_fid = fill_info["orig_fid"]
                                    fill_type = fill_info["sc_type"]

                                    if not _has_usable_geometry(fill_geom):
                                        continue
                                    
                                    # Check distance (tolerance 5cm pro napojení)
                                    try:
                                        dist = null_geom.distanceTo(fill_geom)
                                    except Exception:
                                        continue
                                    
                                    if dist < 0.05: 
                                        # Kde se dotýkají?
                                        connection_point = None
                                        start_pt = null_geom.firstPoint
                                        if start_pt and fill_geom.distanceTo(start_pt) < 0.05:
                                            connection_point = start_pt
                                        else:
                                            end_pt = null_geom.lastPoint
                                            if end_pt and fill_geom.distanceTo(end_pt) < 0.05:
                                                connection_point = end_pt
                                        
                                        if not connection_point:
                                            connection_point = null_geom.firstPoint
                                        
                                        # Je tento bod chráněn bariérou?
                                        is_blocked = False
                                        if barrier_geom and connection_point:
                                            cp_geom = arcpy.PointGeometry(connection_point, null_geom.spatialReference)
                                            if any(bg and not bg.disjoint(cp_geom) for bg in barrier_geom):
                                                # Bariéra nalezena.
                                                type_match = False
                                                if null_type is not None and fill_type is not None:
                                                    if null_type == fill_type:
                                                        type_match = True
                                                elif null_type is None and fill_type is None:
                                                    type_match = True
                                                
                                                if not type_match:
                                                    is_blocked = False
                                                elif null_fid != -1 and fill_fid != -1 and null_fid != fill_fid:
                                                    is_blocked = False
                                                else:
                                                    is_blocked = True
                                        
                                        if not is_blocked:
                                            candidate_attrs = fill_info["attrs"]
                                            break
                                
                                if candidate_attrs:
                                    updates[null_oid] = candidate_attrs
                            
                            # Aplikuj změny do paměti a DB
                            if updates:
                                log_message(f"Iterace {i+1}: Propagováno {len(updates)} segmentů", "DEBUG")
                                
                                # Update DB
                                with arcpy.da.UpdateCursor(r"memory\sc_final_sj", ["OBJECTID"] + available_height_attrs) as cursor:
                                    for row in cursor:
                                        oid = row[0]
                                        if oid in updates:
                                            new_attrs = updates[oid]
                                            for k, val in enumerate(new_attrs):
                                                row[k+1] = val
                                            cursor.updateRow(row)
                                            
                                # Update local cache
                                for oid, new_attrs in updates.items():
                                    segments_data[oid]["attrs"] = new_attrs
                                    segments_data[oid]["has_data"] = True
                            else:
                                log_message(f"Propagace dokončena po {i} iteracích", "OK")
                                break
                            
                    # Cleanup barriers
                    if arcpy.Exists(r"memory\rozhrani_buffer"):
                        arcpy.Delete_management(r"memory\rozhrani_buffer")

                if not has_cad_processing_scope:
                    sc_final_with_vr_cad = r"memory\sc_final_sj"
                    final_count = get_feature_count(sc_final_with_vr_cad)
                    log_message("Bez CAD rozhraní přeskakuji finální dissolve - zachovávám původní linie s napojenými atributy.", "INFO")
                    log_message(f"Finální vrstva bez dissolve: {final_count} segmentů", "OK")
                else:
                    # Dissolve podle TARGET_FID + SC_TYPE + VŠECHNY VÝŠKOVÉ ATRIBUTY
                    log_message("Dissolve pro detekci chyb...", "STEP")
                    
                    # Pro finální dissolve používáme pouze atributy datového modelu výšek.
                    if vr_circles and arcpy.Exists(vr_circles):
                        vr_fields = [f.name for f in arcpy.ListFields(vr_circles)]
                        vr_attributes = [attr for attr in HEIGHT_ATTRIBUTES if attr in vr_fields]
                        # CAD alias: NUP_MAX používáme jako zdroj, pokud NPU_MAX chybí.
                        if "NPU_MAX" not in vr_attributes and "NUP_MAX" in vr_fields:
                            vr_attributes.append("NUP_MAX")
                        log_message(f"VR atributy z bloků pro dissolve: {', '.join(vr_attributes) if vr_attributes else 'žádné'}", "DEBUG")
                    else:
                        vr_attributes = []
                    
                    # Zjisti dostupné výškové atributy v sc_final_sj
                    fields = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                    available_height_attrs = [attr for attr in vr_attributes if attr in fields]
                    
                    log_message(f"Dostupné výškové atributy v finální vrstvě: {', '.join(available_height_attrs)}", "DEBUG")
                    
                    # Statistiky pro VŠECHNY výškové atributy
                    # Dissolve pouze podle TARGET_FID + SC_TYPE → výšky jsou STATS (FIRST + UNIQUE)
                    # Tím vzniknou UNIQUE_ pole pro detekci chyb (více VR bloků na jednom segmentu)
                    stats_fields = []
                    sj_field_names = [f.name for f in arcpy.ListFields(r"memory\sc_final_sj")]
                    for attr in available_height_attrs:
                        stats_fields.append(f"{attr} FIRST")
                        stats_fields.append(f"{attr} UNIQUE")
                    if "ID_LOKAL" in sj_field_names:
                        stats_fields.append("ID_LOKAL FIRST")
                    if "DRUH_SC" in sj_field_names:
                        stats_fields.append("DRUH_SC FIRST")
                    if "DRUH_INFO" in sj_field_names:
                        stats_fields.append("DRUH_INFO FIRST")

                    stats = ";".join(stats_fields) if stats_fields else ""

                    # Dissolve pouze podle TARGET_FID + SC_TYPE (BEZ výškových atributů)
                    dissolve_fields = ["TARGET_FID", "SC_TYPE"]

                    log_message(f"Dissolve fields: {', '.join(dissolve_fields)}", "DEBUG")

                    arcpy.management.Dissolve(
                        in_features=r"memory\sc_final_sj",
                        out_feature_class=r"memory\sc_final_dissolved",
                        dissolve_field=dissolve_fields,
                        statistics_fields=stats,
                        multi_part="SINGLE_PART",
                        unsplit_lines="DISSOLVE_LINES"
                    )

                    # Přejmenuj FIRST_ATTR → ATTR pro přehlednost dalšího zpracování
                    # (AlterField nepodporuje memory workspace → AddField + CalculateField + DeleteField)
                    _type_map = {"String": "TEXT", "Double": "DOUBLE", "Single": "FLOAT",
                                 "Short": "SHORT", "Long": "LONG", "Integer": "LONG", "Date": "DATE"}
                    dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                    _attrs_to_rename = list(dict.fromkeys(available_height_attrs + ["ID_LOKAL", "DRUH_SC", "DRUH_INFO"]))
                    for attr in _attrs_to_rename:
                        first_name = f"FIRST_{attr}"
                        if first_name in dissolved_fields_dict and attr not in dissolved_fields_dict:
                            try:
                                first_field = dissolved_fields_dict[first_name]
                                fld_type = _type_map.get(first_field.type, "TEXT")
                                if first_field.type == "String":
                                    arcpy.management.AddField(r"memory\sc_final_dissolved", attr, fld_type,
                                                              field_length=first_field.length)
                                else:
                                    arcpy.management.AddField(r"memory\sc_final_dissolved", attr, fld_type)
                                arcpy.management.CalculateField(r"memory\sc_final_dissolved", attr,
                                                                f"!{first_name}!", "PYTHON3")
                                arcpy.management.DeleteField(r"memory\sc_final_dissolved", [first_name])
                                dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                            except Exception as e_ren:
                                log_message(f"Přejmenování {first_name} selhalo: {e_ren}", "WARN")

                    # Rename known CAD field name aliases to canonical data model names
                    # NUP_MAX (CAD typo) → NPU_MAX (data model), plus UNIQUE_NUP_MAX → UNIQUE_NPU_MAX
                    dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                    for cad_name, model_name in [("NUP_MAX", "NPU_MAX")]:
                        for _rsrc, _rdst in [(cad_name, model_name),
                                            (f"UNIQUE_{cad_name}", f"UNIQUE_{model_name}")]:
                            if _rsrc in dissolved_fields_dict and _rdst not in dissolved_fields_dict:
                                try:
                                    _rf = dissolved_fields_dict[_rsrc]
                                    _rftype = _type_map.get(_rf.type, "TEXT")
                                    if _rf.type == "String":
                                        arcpy.management.AddField(r"memory\sc_final_dissolved", _rdst, _rftype,
                                                                  field_length=_rf.length)
                                    else:
                                        arcpy.management.AddField(r"memory\sc_final_dissolved", _rdst, _rftype)
                                    arcpy.management.CalculateField(r"memory\sc_final_dissolved", _rdst,
                                                                    f"!{_rsrc}!", "PYTHON3")
                                    arcpy.management.DeleteField(r"memory\sc_final_dissolved", [_rsrc])
                                    dissolved_fields_dict = {f.name: f for f in arcpy.ListFields(r"memory\sc_final_dissolved")}
                                except Exception as e_cad:
                                    log_message(f"Přejmenování CAD aliasu {_rsrc}→{_rdst} selhalo: {e_cad}", "WARN")

                    sc_final_with_vr_cad = r"memory\sc_final_dissolved"
                    final_count = get_feature_count(sc_final_with_vr_cad)
                    log_message(f"Finální vrstva po dissolve: {final_count} segmentů", "OK")
                    
                    # DEBUG - kontrola SC_TYPE po finálním dissolve
                    fields_final = [f.name for f in arcpy.ListFields(sc_final_with_vr_cad)]
                    if "SC_TYPE" in fields_final:
                        sc_types_found = set()
                        with arcpy.da.SearchCursor(sc_final_with_vr_cad, ["SC_TYPE"]) as cursor:
                            for row in cursor:
                                if row[0]:
                                    sc_types_found.add(row[0])
                        log_message(f"SC_TYPE po finálním dissolve: {len(sc_types_found)} typů - {sorted(sc_types_found)}", "DEBUG")
                    else:
                        log_message("VAROVÁNÍ: SC_TYPE CHYBÍ po finálním dissolve!", "WARN")
                    
                    arcpy.Delete_management(r"memory\sc_final_sj")

                # Paralelní NOCAD větev: bez dissolve, jen napojení atributů na původní linie.
                if has_cad_processing_scope and sc_nocad_scope and arcpy.Exists(sc_nocad_scope) and sc_nocad_scope_count > 0:
                    try:
                        log_message(
                            f"Zpracovávám NOCAD větev ({sc_nocad_scope_count} linií) s unikátním párováním VR bloků do {NOCAD_VR_ASSIGN_TOLERANCE_METERS:.2f} m...",
                            "STEP"
                        )
                        build_unique_line_block_assignment(
                            sc_nocad_scope,
                            vr_join_for_sj,
                            r"memory\sc_nocad_sj",
                            attrs_to_fix,
                            tolerance_meters=NOCAD_VR_ASSIGN_TOLERANCE_METERS,
                            log_label="NOCAD větev"
                        )
                        sc_final_with_vr_nocad = r"memory\sc_nocad_sj"
                        log_message(f"NOCAD větev připravena: {get_feature_count(sc_final_with_vr_nocad)} segmentů", "OK")
                    except Exception as nocad_error:
                        log_message(f"Chyba při zpracování NOCAD větve: {nocad_error}", "WARN")

                # Sloučení větví do jedné finální vrstvy pro export.
                if sc_final_with_vr_cad and arcpy.Exists(sc_final_with_vr_cad) and sc_final_with_vr_nocad and arcpy.Exists(sc_final_with_vr_nocad):
                    for _fc, _mode in [(sc_final_with_vr_cad, "CAD"), (sc_final_with_vr_nocad, "NOCAD")]:
                        _fields = [f.name for f in arcpy.ListFields(_fc)]
                        if "_CAD_MODE" not in _fields:
                            arcpy.management.AddField(_fc, "_CAD_MODE", "TEXT", field_length=10)
                        with arcpy.da.UpdateCursor(_fc, ["_CAD_MODE"]) as _cur:
                            for _row in _cur:
                                _row[0] = _mode
                                _cur.updateRow(_row)

                    arcpy.management.Merge(
                        inputs=[sc_final_with_vr_cad, sc_final_with_vr_nocad],
                        output=r"memory\sc_final_combined"
                    )
                    sc_final_with_vr = r"memory\sc_final_combined"
                    log_message(
                        f"Finální hybrid vrstva: CAD {get_feature_count(sc_final_with_vr_cad)} + NOCAD {get_feature_count(sc_final_with_vr_nocad)} = {get_feature_count(sc_final_with_vr)}",
                        "OK"
                    )
                elif sc_final_with_vr_cad and arcpy.Exists(sc_final_with_vr_cad):
                    sc_final_with_vr = sc_final_with_vr_cad
                elif sc_final_with_vr_nocad and arcpy.Exists(sc_final_with_vr_nocad):
                    sc_final_with_vr = sc_final_with_vr_nocad
                else:
                    sc_final_with_vr = sc_cleaned
                
            except Exception as e:
                log_message(f"Chyba při finálním připojení atributů: {e}", "ERROR")
                sc_final_with_vr = sc_cleaned
        else:
            # Pokud nejsou VR bloky, použij jen vyčištěné SC
            log_message("VR bloky nebyly nalezeny - pokračuji bez výškových atributů", "WARN")
            sc_final_with_vr = sc_cleaned
        
        # ============================================================
        # FÁZE 9: TVORBA VÝSTUPNÍCH VRSTEV DLE DATOVÉHO MODELU
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 9: TVORBA VÝSTUPNÍCH VRSTEV DLE DATOVÉHO MODELU", "STEP")
        log_message("=" * 60, "INFO")

        final_outputs = []
        errors_outputs = []

        if sc_final_with_vr:
            try:
                fields_in_final = [f.name for f in arcpy.ListFields(sc_final_with_vr)]

                # Zjisti, které výškové atributy jsou dostupné ve výsledné vrstvě
                available_height_attrs_final = get_model_height_attributes(fields_in_final)
                log_message(f"Dostupné výškové atributy ve finální vrstvě: {', '.join(available_height_attrs_final)}", "DEBUG")

                if available_height_attrs_final:
                    without_block_count = 0
                    with arcpy.da.SearchCursor(sc_final_with_vr, available_height_attrs_final) as cursor:
                        for row in cursor:
                            if all(_is_missing_value(v) or _is_zero_like_value(v) for v in row):
                                without_block_count += 1
                    if without_block_count > 0:
                        log_message(f"Segmentů bez výškového bloku: {without_block_count} (informace, ne chyba)", "CHECK")
                    else:
                        log_message("Všechny segmenty mají přiřazený výškový blok", "OK")

                # --------------------------------------------------------
                # 9A: Z_3011_StavebniCara_l
                # Čistá geometrie SC (dissolve bez výškových atributů),
                # s DRUH_SC mapovaným z SC_TYPE a atributy datového modelu.
                # --------------------------------------------------------
                log_message("Tvořím Z_3011_StavebniCara_l...", "STEP")

                try:
                    # Dissolve všech SC segmentů podle SC_TYPE (zachová typ čáry, sloučí segmenty)
                    arcpy.management.Dissolve(
                        in_features=sc_final_with_vr,
                        out_feature_class=r"memory\sc_3011_dissolve",
                        dissolve_field=["SC_TYPE"],
                        statistics_fields=None,
                        multi_part="SINGLE_PART",
                        unsplit_lines="DISSOLVE_LINES"
                    )

                    sc_3011_name = f"{out_prefix}3011_StavebniCara_l" if out_prefix else "Z_3011_StavebniCara_l"
                    sc_3011_name = generate_unique_name(output_gdb, sc_3011_name)
                    sc_3011_fc = os.path.join(output_workspace, sc_3011_name)

                    arcpy.conversion.ExportFeatures(r"memory\sc_3011_dissolve", sc_3011_fc)
                    arcpy.Delete_management(r"memory\sc_3011_dissolve")

                    # Přidat atributy datového modelu
                    arcpy.management.AddField(sc_3011_fc, "SKNAZEV", "TEXT", field_length=50)
                    arcpy.management.AddField(sc_3011_fc, "OBTYPNAZEV", "TEXT", field_length=50)
                    arcpy.management.AddField(sc_3011_fc, "DRUH_SC", "TEXT", field_length=10)
                    arcpy.management.AddField(sc_3011_fc, "DRUH_INFO", "TEXT", field_length=255)
                    arcpy.management.AddField(sc_3011_fc, "ID_LOKAL", "SHORT")

                    # Naplnit atributy
                    with arcpy.da.UpdateCursor(sc_3011_fc, ["SC_TYPE", "SKNAZEV", "OBTYPNAZEV", "DRUH_SC"]) as cursor:
                        for row in cursor:
                            row[1] = "regulace struktury"
                            row[2] = "stavební čára"
                            row[3] = get_druh_sc_from_sc_type(row[0])
                            cursor.updateRow(row)

                    # Přenést DRUH_INFO z původní vrstvy (pokud existuje)
                    if "DRUH_INFO" in fields_in_final:
                        sc_3011_fields = [f.name for f in arcpy.ListFields(sc_3011_fc)]
                        if "DRUH_INFO" in sc_3011_fields:
                            # DRUH_INFO je prázdné, přenést z merged_sc_all pokud dostupné
                            try:
                                druh_info_map = {}
                                with arcpy.da.SearchCursor(sc_final_with_vr, ["SC_TYPE", "DRUH_INFO"]) as sc:
                                    for r in sc:
                                        if r[0] and r[1]:
                                            druh_info_map[r[0]] = r[1]
                                with arcpy.da.UpdateCursor(sc_3011_fc, ["SC_TYPE", "DRUH_INFO"]) as uc:
                                    for r in uc:
                                        if r[0] in druh_info_map:
                                            r[1] = druh_info_map[r[0]]
                                            uc.updateRow(r)
                            except Exception as e_di:
                                log_message(f"Přenos DRUH_INFO selhal: {e_di}", "WARN")

                    finalize_vyska_output_attributes(sc_3011_fc, "Z_3011_StavebniCara_l")

                    sc_3011_count = get_feature_count(sc_3011_fc)
                    log_message(f"Z_3011_StavebniCara_l: {sc_3011_count} prvků → {sc_3011_name}", "OK")
                    final_outputs.append(sc_3011_fc)

                except Exception as e:
                    log_message(f"Chyba při tvorbě Z_3011_StavebniCara_l: {e}", "ERROR")

                # --------------------------------------------------------
                # 9B: Z_3022_VyskovaRegulaceNaLinii_l
                # Všechny SC segmenty (i bez výšky), s výškovými atributy
                # přiřazenými spatial joinem. Obsahuje i NULL segmenty.
                # Detekce chyb: segmenty s více než jedním VR blokem.
                # --------------------------------------------------------
                log_message("Tvořím Z_3022_VyskovaRegulaceNaLinii_l...", "STEP")

                try:
                    vr_3022_name = f"{out_prefix}3022_VyskovaRegulaceNaLinii_l" if out_prefix else "Z_3022_VyskovaRegulaceNaLinii_l"
                    vr_3022_name = generate_unique_name(output_gdb, vr_3022_name)
                    vr_3022_fc = os.path.join(output_workspace, vr_3022_name)

                    if has_cad_processing_scope:
                        # Dissolve aplikujeme pouze na CAD část. NOCAD část jde ven bez dissolve.
                        dissolve_fields_3022 = available_height_attrs_final if available_height_attrs_final else []

                        stats_3022 = []
                        if "ID_LOKAL" in fields_in_final:
                            stats_3022.append("ID_LOKAL FIRST")
                        for attr in available_height_attrs_final:
                            unique_fname = f"UNIQUE_{attr}"
                            if unique_fname in fields_in_final:
                                stats_3022.append(f"{unique_fname} MAX")

                        parts_to_merge = []
                        has_mode_field = "_CAD_MODE" in [f.name for f in arcpy.ListFields(sc_final_with_vr)]

                        if has_mode_field:
                            arcpy.management.MakeFeatureLayer(sc_final_with_vr, "sc_3022_src_lyr")
                            try:
                                arcpy.management.SelectLayerByAttribute(
                                    in_layer_or_view="sc_3022_src_lyr",
                                    selection_type="NEW_SELECTION",
                                    where_clause="_CAD_MODE = 'CAD'"
                                )
                                cad_count = int(arcpy.GetCount_management("sc_3022_src_lyr")[0])
                                if cad_count > 0:
                                    arcpy.conversion.ExportFeatures("sc_3022_src_lyr", r"memory\sc_3022_cad_input")
                                    arcpy.management.Dissolve(
                                        in_features=r"memory\sc_3022_cad_input",
                                        out_feature_class=r"memory\sc_3022_cad_dissolve",
                                        dissolve_field=dissolve_fields_3022,
                                        statistics_fields=";".join(stats_3022) if stats_3022 else "",
                                        multi_part="SINGLE_PART",
                                        unsplit_lines="DISSOLVE_LINES"
                                    )
                                    parts_to_merge.append(r"memory\sc_3022_cad_dissolve")

                                arcpy.management.SelectLayerByAttribute(
                                    in_layer_or_view="sc_3022_src_lyr",
                                    selection_type="NEW_SELECTION",
                                    where_clause="_CAD_MODE = 'NOCAD'"
                                )
                                nocad_count = int(arcpy.GetCount_management("sc_3022_src_lyr")[0])
                                if nocad_count > 0:
                                    arcpy.conversion.ExportFeatures("sc_3022_src_lyr", r"memory\sc_3022_nocad_input")
                                    parts_to_merge.append(r"memory\sc_3022_nocad_input")
                            finally:
                                arcpy.management.Delete("sc_3022_src_lyr")
                        else:
                            arcpy.management.Dissolve(
                                in_features=sc_final_with_vr,
                                out_feature_class=r"memory\sc_3022_cad_dissolve",
                                dissolve_field=dissolve_fields_3022,
                                statistics_fields=";".join(stats_3022) if stats_3022 else "",
                                multi_part="SINGLE_PART",
                                unsplit_lines="DISSOLVE_LINES"
                            )
                            parts_to_merge.append(r"memory\sc_3022_cad_dissolve")

                        if len(parts_to_merge) > 1:
                            arcpy.management.Merge(parts_to_merge, r"memory\sc_3022_dissolve")
                            arcpy.conversion.ExportFeatures(r"memory\sc_3022_dissolve", vr_3022_fc)
                        elif len(parts_to_merge) == 1:
                            arcpy.conversion.ExportFeatures(parts_to_merge[0], vr_3022_fc)
                        else:
                            arcpy.conversion.ExportFeatures(sc_final_with_vr, vr_3022_fc)
                    else:
                        log_message("Bez CAD rozhraní exportuji Z_3022 bez dissolve (původní linie + napojené atributy).", "INFO")
                        arcpy.conversion.ExportFeatures(sc_final_with_vr, vr_3022_fc)

                    # Přejmenuj FIRST_ pole zpět na čistá jména a přidej atributy datového modelu
                    vr_3022_fields = [f.name for f in arcpy.ListFields(vr_3022_fc)]

                    # Výškové atributy jsou dissolve fields → jsou přímo jako VYSKA_VB, RIMSA_MAX atd.
                    # Přejmenovat jen FIRST_ID_LOKAL → ID_LOKAL (ID_LOKAL bylo v stats)
                    for attr in ["ID_LOKAL"]:
                        first_name = f"FIRST_{attr}"
                        if first_name in vr_3022_fields and attr not in vr_3022_fields:
                            arcpy.management.AlterField(vr_3022_fc, first_name, attr, attr)

                    # Aktualizuj seznam polí po přejmenování
                    vr_3022_fields = [f.name for f in arcpy.ListFields(vr_3022_fc)]

                    # Přidat SKNAZEV a OBTYPNAZEV pokud chybí
                    if "SKNAZEV" not in vr_3022_fields:
                        arcpy.management.AddField(vr_3022_fc, "SKNAZEV", "TEXT", field_length=50)
                    if "OBTYPNAZEV" not in vr_3022_fields:
                        arcpy.management.AddField(vr_3022_fc, "OBTYPNAZEV", "TEXT", field_length=50)
                    if "ID_LOKAL" not in vr_3022_fields:
                        arcpy.management.AddField(vr_3022_fc, "ID_LOKAL", "SHORT")

                    # Zajisti úplné schéma výškových atributů dle datového modelu.
                    model_field_specs = {
                        "VYSKA_VB": ("TEXT", 10),
                        "VYSKA_VB_I": ("TEXT", 255),
                        "NP_MIN": ("SHORT", None),
                        "NP_MAX": ("SHORT", None),
                        "NPU_MAX": ("SHORT", None),
                        "RIMSA_MIN": ("FLOAT", None),
                        "RIMSA_MAX": ("FLOAT", None),
                        "VYSKA_MAX": ("FLOAT", None),
                    }

                    # Alias NUP_MAX -> NPU_MAX (vždy doplň prázdné hodnoty do datového modelu).
                    ensure_npu_from_nup(vr_3022_fc)

                    vr_3022_fields = [f.name for f in arcpy.ListFields(vr_3022_fc)]
                    for fname, (ftype, flen) in model_field_specs.items():
                        if fname not in vr_3022_fields:
                            if flen:
                                arcpy.management.AddField(vr_3022_fc, fname, ftype, field_length=flen)
                            else:
                                arcpy.management.AddField(vr_3022_fc, fname, ftype)

                    with arcpy.da.UpdateCursor(vr_3022_fc, ["SKNAZEV", "OBTYPNAZEV"]) as cursor:
                        for row in cursor:
                            row[0] = "regulace struktury"
                            row[1] = "výšková regulace na linii"
                            cursor.updateRow(row)

                    with arcpy.da.UpdateCursor(vr_3022_fc, ["ID_LOKAL"]) as cursor:
                        for row in cursor:
                            if row[0] is None:
                                row[0] = 0
                                cursor.updateRow(row)

                    # Smazat nadbytečná pole - zachovat jen pole datového modelu
                    # + MAX_UNIQUE_* pole (potřebná pro error detection níže, smažou se po detekci)
                    keep_3022 = {"SKNAZEV", "OBTYPNAZEV", "ID_LOKAL",
                                 "VYSKA_VB", "VYSKA_VB_I",
                                 "NP_MIN", "NP_MAX", "NPU_MAX",
                                 "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX"}
                    vr_3022_fields_now = [f.name for f in arcpy.ListFields(vr_3022_fc)]
                    del_3022 = []
                    for fn in vr_3022_fields_now:
                        if fn in keep_3022:
                            continue
                        # Zachovat MAX_UNIQUE_* pro error detection (smažou se po detekci chyb)
                        if fn.startswith("MAX_UNIQUE_"):
                            continue
                        fi = arcpy.ListFields(vr_3022_fc, fn)[0]
                        if fi.required or fi.type in ("OID", "Geometry"):
                            continue
                        if fn.lower() in ("shape_length", "shape_area"):
                            continue
                        del_3022.append(fn)
                    if del_3022:
                        arcpy.management.DeleteField(vr_3022_fc, del_3022)

                    # --------------------------------------------------------
                    # 9C: Z_3022_VyskovaRegulaceNaLinii_l_Errors
                    # Segmenty s více než jedním přiřazeným VR blokem
                    # (detekováno přes UNIQUE_RIMSA_MAX nebo UNIQUE jiného atributu > 1)
                    # --------------------------------------------------------
                    try:
                        # Detekce chyb: MAX_UNIQUE_ATTR > 1 = na alespoň jednom sub-segmentu
                        # bylo více VR bloků s různými hodnotami
                        unique_fields_in_vr = [f.name for f in arcpy.ListFields(vr_3022_fc)
                                               if f.name.startswith("MAX_UNIQUE_")]
                        if unique_fields_in_vr:
                            error_where = " OR ".join([f"{uf} > 1" for uf in unique_fields_in_vr])
                            # MakeFeatureLayer required: GetCount + ExportFeatures respect selection
                            # only when operating on a named layer, not a bare feature class path.
                            _err_lyr = "_vr3022_err_check"
                            arcpy.management.MakeFeatureLayer(vr_3022_fc, _err_lyr)
                            try:
                                arcpy.management.SelectLayerByAttribute(
                                    in_layer_or_view=_err_lyr,
                                    selection_type="NEW_SELECTION",
                                    where_clause=error_where
                                )
                                err_count = int(arcpy.GetCount_management(_err_lyr)[0])

                                if err_count > 0:
                                    vr_err_name = f"{out_prefix}3022_VyskovaRegulaceNaLinii_l_Errors" if out_prefix else "Z_3022_VyskovaRegulaceNaLinii_l_Errors"
                                    vr_err_name = generate_unique_name(output_gdb, vr_err_name)
                                    vr_err_fc = os.path.join(output_workspace, vr_err_name)
                                    arcpy.conversion.ExportFeatures(_err_lyr, vr_err_fc)
                                    log_message(f"Z_3022_Errors: {err_count} chybných segmentů → {vr_err_name}", "CHECK")
                                    errors_outputs.append(vr_err_fc)
                                else:
                                    log_message("Z_3022: Žádné chyby (všechny segmenty mají max. 1 VR blok)", "OK")
                            finally:
                                arcpy.management.Delete(_err_lyr)

                            # Smazat UNIQUE_ pole z výsledné vrstvy (jsou jen pro interní detekci chyb)
                            arcpy.management.DeleteField(vr_3022_fc, unique_fields_in_vr)

                    except Exception as e_err:
                        log_message(f"Chyba při tvorbě vrstvy chyb Z_3022: {e_err}", "WARN")

                    finalize_vyska_output_attributes(vr_3022_fc, "Z_3022_VyskovaRegulaceNaLinii_l")
                    vr_3022_count = get_feature_count(vr_3022_fc)
                    log_message(f"Z_3022_VyskovaRegulaceNaLinii_l: {vr_3022_count} prvků → {vr_3022_name}", "OK")
                    final_outputs.append(vr_3022_fc)

                except Exception as e:
                    log_message(f"Chyba při tvorbě Z_3022_VyskovaRegulaceNaLinii_l: {e}", "ERROR")

                # --------------------------------------------------------
                # 9D: Export VR_NA_BOD (pokud existuje)
                # --------------------------------------------------------
                if vr_na_bod_layer and arcpy.Exists(vr_na_bod_layer):
                    try:
                        out_name_bod = f"{out_prefix}3021_VyskovaRegulaceNaBod_b" if out_prefix else "Z_3021_VyskovaRegulaceNaBod_b"
                        out_name_bod = generate_unique_name(output_gdb, out_name_bod)
                        out_fc_bod = os.path.join(output_workspace, out_name_bod)

                        # VR na bod exportujeme jako centroidní body místo linií.
                        vr_na_bod_centroid = r"memory\tmp_vr_na_bod_centroid"
                        if arcpy.Exists(vr_na_bod_centroid):
                            arcpy.management.Delete(vr_na_bod_centroid)
                        arcpy.management.FeatureToPoint(
                            in_features=vr_na_bod_layer,
                            out_feature_class=vr_na_bod_centroid,
                            point_location="CENTROID"
                        )

                        # U soustředných kružnic může vzniknout stejný centroid vícekrát.
                        try:
                            arcpy.management.DeleteIdentical(vr_na_bod_centroid, ["Shape"])
                        except Exception as e_del_ident:
                            log_message(f"Nelze odstranit duplicitní centroidy VR na bod: {e_del_ident}", "DEBUG")

                        arcpy.conversion.ExportFeatures(vr_na_bod_centroid, out_fc_bod)
                        ensure_canonical_vr_fields(out_fc_bod)

                        # Přidat SKNAZEV, OBTYPNAZEV
                        arcpy.management.AddField(out_fc_bod, "SKNAZEV", "TEXT", field_length=50)
                        arcpy.management.AddField(out_fc_bod, "OBTYPNAZEV", "TEXT", field_length=50)
                        if "ID_LOKAL" not in [f.name for f in arcpy.ListFields(out_fc_bod)]:
                            arcpy.management.AddField(out_fc_bod, "ID_LOKAL", "SHORT")

                        # Alias NUP_MAX -> NPU_MAX (vždy doplň prázdné hodnoty do datového modelu).
                        ensure_npu_from_nup(out_fc_bod)

                        # Zajisti úplné schéma výškové regulace na bod.
                        model_bod_specs = {
                            "VYSKA_VB": ("TEXT", 10),
                            "VYSKA_VB_I": ("TEXT", 255),
                            "NP_MIN": ("SHORT", None),
                            "NP_MAX": ("SHORT", None),
                            "NPU_MAX": ("SHORT", None),
                            "RIMSA_MIN": ("FLOAT", None),
                            "RIMSA_MAX": ("FLOAT", None),
                            "VYSKA_MAX": ("FLOAT", None),
                        }
                        out_bod_fields = [f.name for f in arcpy.ListFields(out_fc_bod)]
                        for fname, (ftype, flen) in model_bod_specs.items():
                            if fname not in out_bod_fields:
                                if flen:
                                    arcpy.management.AddField(out_fc_bod, fname, ftype, field_length=flen)
                                else:
                                    arcpy.management.AddField(out_fc_bod, fname, ftype)

                        with arcpy.da.UpdateCursor(out_fc_bod, ["SKNAZEV", "OBTYPNAZEV"]) as cur:
                            for row in cur:
                                row[0] = "regulace struktury"
                                row[1] = "výšková regulace na bod"
                                cur.updateRow(row)

                        with arcpy.da.UpdateCursor(out_fc_bod, ["ID_LOKAL"]) as cur:
                            for row in cur:
                                if row[0] is None:
                                    row[0] = 0
                                    cur.updateRow(row)

                        # Odstranit pole mimo datový model.
                        keep_bod = {
                            "SKNAZEV", "OBTYPNAZEV", "ID_LOKAL",
                            "VYSKA_VB", "VYSKA_VB_I",
                            "NP_MIN", "NP_MAX", "NPU_MAX",
                            "RIMSA_MIN", "RIMSA_MAX", "VYSKA_MAX"
                        }
                        fields_to_delete_bod = []
                        for field in arcpy.ListFields(out_fc_bod):
                            if field.name in keep_bod:
                                continue
                            if field.required or field.type in ("OID", "Geometry"):
                                continue
                            if field.name.lower() in ("shape_length", "shape_area"):
                                continue
                            fields_to_delete_bod.append(field.name)
                        if fields_to_delete_bod:
                            arcpy.management.DeleteField(out_fc_bod, fields_to_delete_bod)

                        finalize_vyska_output_attributes(out_fc_bod, "Z_3021_VyskovaRegulaceNaBod_b")

                        final_outputs.append(out_fc_bod)
                        log_message(f"Z_3021_VyskovaRegulaceNaBod_b: exportováno → {out_name_bod}", "OK")

                        if arcpy.Exists(vr_na_bod_centroid):
                            arcpy.management.Delete(vr_na_bod_centroid)
                    except Exception as e:
                        log_message(f"Chyba při exportu VR na bod: {e}", "WARN")

            except Exception as e:
                log_message(f"Kritická chyba ve Fázi 9: {e}", "ERROR")

        # ============================================================
        # FÁZE 10: CLEANUP
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("FÁZE 10: CLEANUP DOČASNÝCH VRSTEV", "STEP")
        log_message("=" * 60, "INFO")
        
        # Export rozhraní pro kontrolu - DISABLED
        # if rozhrani_body_all and arcpy.Exists(rozhrani_body_all): ...
        
        # Export CAD linie rozhraní pro kontrolu - DISABLED FOR FINAL CLEANUP
        # if vr_rozhrani_layer and arcpy.Exists(vr_rozhrani_layer):
        #     try:
        #         if out_prefix:
        #             rozhrani_line_name = f"{out_prefix}Rozhrani_linie_CAD"
        #         else:
        #             rozhrani_line_name = "Z_Rozhrani_linie_CAD"
        #         
        #         rozhrani_line_name = generate_unique_name(output_gdb, rozhrani_line_name)
        #         rozhrani_line_output = os.path.join(output_workspace, rozhrani_line_name)
        #         
        #         arcpy.CopyFeatures_management(vr_rozhrani_layer, rozhrani_line_output)
        #         rozhrani_line_count = get_feature_count(rozhrani_line_output)
        #         log_message(f"Export CAD linií rozhraní: {rozhrani_line_name} ({rozhrani_line_count} linií)", "DEBUG")
        #     except Exception as e:
        #         log_message(f"Nepodařilo se exportovat CAD linie rozhraní: {e}", "WARN")
        
        # Seznam memory vrstev k smazání
        memory_layers = [
            r"memory\sc_all_merged",
            r"memory\sc_cad_scope",
            r"memory\sc_nocad_scope",
            r"memory\rozhrani_body_cad",
            r"memory\rozhrani_all",
            r"memory\vr_block_split_points",
            r"memory\vr_join_points",
            r"memory\split_points_phase3",
            r"memory\split_points_phase6",
            r"memory\sc_split_cad",
            r"memory\sc_with_vr",
            r"memory\sc_with_vr_temp",
            r"memory\sc_nocad_sj",
            r"memory\sc_final_sj",
            r"memory\sc_final_dissolved",
            r"memory\sc_final_combined",
            r"memory\sc_dissolve_clean",
            r"memory\sc_final_split",
            r"memory\sc_cleaned",
            r"memory\vr_linii_singlepart",
            r"memory\rozhrani_body_multipart",
            r"memory\rozhrani_lines_snap",
            r"memory\sc_3011_dissolve",
            r"memory\sc_3022_dissolve",
            r"memory\sc_3022_cad_input",
            r"memory\sc_3022_cad_dissolve",
            r"memory\sc_3022_nocad_input",
            r"memory\cleanup_boundary_points",
            r"memory\sc_cad_scope_seed",
            r"memory\sc_cad_scope_expand",
            r"memory\tmp_vr_na_bod_centroid",
            r"memory\rozhrani_endpoints",
            r"memory\sc_cleaned_fresh",
            r"memory\vr_join_phase8",
        ]
        
        deleted = 0
        for mem_layer in memory_layers:
            if arcpy.Exists(mem_layer):
                try:
                    arcpy.Delete_management(mem_layer)
                    deleted += 1
                except:
                    pass
        
        log_message(f"Smazáno {deleted} dočasných vrstev z paměti", "OK")
        
        # Smazání pomocných vrstev z output workspace (importované vrstvy a dočasné mezivýsledky)
        deleted_gdb = 0
        try:
            # Smazání pomocných vrstev VR bloků a rozhraní
            layers_to_delete = [vr_rozhrani_layer, vr_na_bod_layer, vr_na_linii_layer, vr_circles]
            
            for layer in layers_to_delete:
                if layer and arcpy.Exists(layer):
                    arcpy.Delete_management(layer)
                    deleted_gdb += 1
                    
            # Smazání původních SC vrstev (jsou nahrazeny finálními výstupy s SC_TYPE)
            for sc_layer in sc_layers:
                if arcpy.Exists(sc_layer):
                    arcpy.Delete_management(sc_layer)
                    deleted_gdb += 1
        except Exception as e:
            log_message(f"Chyba při mazání pomocných vrstev v GDB: {e}", "WARN")
            
        log_message(f"Smazáno {deleted_gdb} importovaných vrstev z GDB", "OK")

        # ============================================================
        # SHRNUTÍ
        # ============================================================
        log_message("=" * 60, "INFO")
        log_message("HOTOVO!", "OK")
        log_message("=" * 60, "INFO")
        
        if final_outputs:
            log_message(f"Vytvořeno {len(final_outputs)} výstupních vrstev:", "OK")
            for output_path in final_outputs:
                log_message(f"  • {os.path.basename(output_path)}", "OK")
        
        if errors_outputs:
            log_message(f"Vrstvy s chybami ({len(errors_outputs)}):", "CHECK")
            for error_path in errors_outputs:
                log_message(f"  • {os.path.basename(error_path)}", "CHECK")
        
        log_message(f"Output GDB: {output_gdb}", "INFO")

