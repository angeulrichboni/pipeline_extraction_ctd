"""Clean, classify and audit the merged association table."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.io.csv_io import read_csv_rows, write_csv_rows
from src.io.json_io import write_json


# Constants

QC_COLUMNS = [
    "qc_decision",
    "qc_role",
    "qc_measure_status",
    "qc_exposure_status",
    "qc_outcome_status",
    "qc_result_context",
    "qc_include_in_clean_database",
    "qc_include_in_clean_main_analysis",
    "qc_reasons",
]

AUDIT_COLUMNS = [
    "metric",
    "value",
]

PROJECT_TARGET_KEYS = {
    "pm",
    "pm25",
    "pm10",
    "pm1",
    "ufp",
    "no",
    "no2",
    "o3",
    "ozone",
}

CONTEXTUAL_AIR_POLLUTANT_KEYS = {
    "co",
    "carbonmonoxide",
    "so2",
    "sulfurdioxide",
    "sulphurdioxide",
    "nox",
    "nitrogenoxides",
    "blackcarbon",
    "blacksmoke",
    "blacksmokebs",
    "elementalcarbon",
    "elementalcarbonec",
    "ec",
    "soot",
    "h2s",
    "hydrogensulfide",
    "trafficrelatedpollution",
    "trafficrelatedpollutants",
    "trafficrelatedairpollution",
    "trp",
    "trap",
    "roadproximity",
    "roadwayproximity",
    "diesel",
    "dieselexhaust",
    "exhaust",
    "vehicleexhaust",
    "trafficexhaust",
    "industrialpollution",
    "occupationalparticulateexposure",
    "weldingfumes",
    "weldingfume",
    "wildfiresmoke",
    "smokeevents",
    "woodsmoke",
    "biomasssmoke",
    "biomassfuels",
    "biomassfueluse",
    "biomassburning",
    "environmentaltobaccosmoke",
    "environmentaltobaccosmokeets",
    "ets",
    "secondhandsmoke",
    "secondhandsmokeshs",
    "shs",
    "passivesmoking",
    "serumcotinine",
    "urinarycotinine",
    "cotinine",
    "benzene",
    "pah",
    "pahs",
    "polycyclicaromatichydrocarbons",
    "sulfate",
    "nitrate",
    "vanadium",
    "particlenumber",
    "particlenumberconcentration",
    "particlenumberconcentrations",
    "nc002",
    "nc0021",
    "ufpaviation",
    "tsp",
    "totalsuspendedparticulates",
    "spm",
    "suspendedparticulatematter",
    "bs",
    "bc",
    "oc",
    "organiccarbon",
    "caps",
    "finecaps",
    "coarsecaps",
    "concentratedambientparticles",
    "pnc",
    "duststorms",
    "asianduststorms",
    "ads",
    "desertdust",
    "formaldehyde",
    "hcho",
    "incensesmoke",
    "cooksmoke",
    "cookingsmoke",
    "cookingfuel",
    "kerosene",
    "gasresidentialcookingfuel",
    "residentialcookingfuel",
    "solidfuels",
    "solidfuelsbiomass",
    "mosquitocoils",
    "iapcc",
    "indoorairpollutioncoalcombustion",
    "combustionproducts",
    "coalfiredpowerplant",
    "coalfiredpowerplants",
    "powerplantemissions",
    "methaneemissions",
    "trafficintensity",
    "trafficvolume",
    "roadlength",
    "lengthofroads",
    "lengthoflocalroads",
    "trucksnearhomes",
    "truckspassingnearhomes",
    "pmcoarse",
    "rec",
    "respirableelementalcarbon",
    "respirabledust",
    "inorganicdust",
    "occupationaldustexposure",
    "occupationaldust",
    "cottondust",
    "dustweathercondition",
    "dieseltractoruse",
    "emissionsfromincinerators",
    "oilgaswells",
    "oilandgaswells",
    "complexsourcezonepollution",
    "limitedlocaldispersiondays",
    "airmassorigin",
    "sulfur",
    "s",
    "manganese",
    "mn",
    "highsulfurfuelcombustion",
    "secondaryorganics",
}

NON_AIR_POLLUTION_TERMS = {
    "arsenic",
    "ias",
    "inorganic arsenic",
    "drinking water",
    "water ias",
    "daily ias",
    "peak ias",
    "average ias",
    "arsenic exposure",
    "mold",
    "fungi",
    "fungus",
    "cat allergen",
    "dog allergen",
    "cockroach allergen",
    "cockroaches",
    "cockroach",
    "bla g 1",
    "doctor-diagnosed allergies",
    "doctor diagnosed allergies",
    "personal history of hay fever",
    "family history of atopy",
    "hay fever",
    "atopy",
    "alternaria sensitization",
    "penicillium sensitization",
    "cladosporium sensitization",
    "endotoxin",
    "occupational endotoxin exposure",
    "child care center attendance",
    "child-care center attendance",
    "day care attendance",
    "day-care attendance",
    "sharing a bedroom",
    "male sex",
    "female sex",
    "sex",
    "temperature",
    "ambient temperature",
    "heat",
    "cold",
    "herbicide",
    "herbicides",
    "pesticide",
    "pesticides",
    "metolachlor",
    "pendimethalin",
    "chlorpyrifos",
    "diazinon",
    "farm crops",
    "farm animals",
    "farm dust",
    "house dust-derived beta-glucan",
    "house dust derived beta glucan",
    "acrylamide",
    "bde-153",
    "bde 153",
    "polybrominated diphenyl ether",
    "co2",
    "co₂",
    "carbon dioxide",
    "maternal smoking",
    "maternal smoking during pregnancy",
    "active smoking",
    "personal smoking",
    "smoking status",
    "tobacco use",
    "chlorination disinfection by-products",
    "chlorination disinfection by products",
    "cdbps",
    "municipal water",
    "nonmunicipal water",
    "persistent organic pollutants",
    "pops",
    "other types of wastes",
    "hazardous waste",
    "asbestos",
    "chlorinated solvents",
    "trichloroethylene",
    "vinyl chloride",
    "cadmium",
    "mercury",
    "lead",
    "blood lead",
    "blood lead concentration",
    "blood lead levels",
    "glycidamide",
    "glycidamide adducts",
    "infectious mononucleosis",
    "current wheeze proxy",
    "asthma medication use",
    "physical activity",
    "no flush toilet",
    "older age",
    "age",
    "day-of-week",
    "day of week",
    "monday",
    "c3c",
    "methylation",
    "control medical air",
    "control (medical air)",
    "hiv",
    "fried food consumption",
    "coffee consumption",
    "fish consumption",
    "hormone replacement therapy",
    "recurrent urinary tract infections",
    "employment in high-risk occupations",
    "employment in high risk occupations",
    "nonmalignant respiratory disease",
    "lung mass",
    "fetal vascular thrombosis",
    "ftv",
    "cord blood ft4",
    "cord blood ft3",
    "cord blood tsh",
    "solar radiation",
    "sodium",
    "ndvi",
    "phthalate",
    "phthalates",
    "dehp",
    "bbzp",
    "dep",
    "diethyl phthalate",
    "dibutyl phthalate",
    "butylbenzyl phthalate",
    "di(2-ethylhexyl) phthalate",
    "vinyl flooring",
    "snuff use",
    "food consumption",
    "fat intake",
}

COVARIATE_EXPOSURE_TERMS = {
    "maternal age",
    "prenatal vitamin",
    "vitamin use",
    "bmi",
    "body mass index",
    "education",
    "income",
    "child care",
    "day care",
    "bedroom sharing",
    "sharing a bedroom",
    "male sex",
    "female sex",
    "sex",
    "older age",
    "age",
    "physical activity",
}

TARGET_AIR_POLLUTION_PATTERNS = [
    "pm2.5",
    "pm 2.5",
    "pm25",
    "pm₂.₅",
    "pm10",
    "pm 10",
    "pm1",
    "pm 1",
    "pmcoarse",
    "pm coarse",
    "particulate matter",
    "particulate air pollution",
    "fine particulate",
    "fine particles",
    "coarse particles",
    "ultrafine particles",
    "ultrafine particle",
    "ufp",
    "nitric oxide",
    "nitrogen dioxide",
    "no2",
    "no₂",
    "ozone",
    "o3",
    "o₃",
]

TARGET_AIR_POLLUTION_COMPACT_PATTERNS = {
    "pm25",
    "pm10",
    "pm1",
    "pmcoarse",
    "particulatematter",
    "fineparticulate",
    "fineparticles",
    "coarseparticles",
    "ultrafineparticles",
    "ufp",
    "nitricoxide",
    "nitrogendioxide",
    "no2",
    "ozone",
    "o3",
}

CONTEXTUAL_AIR_POLLUTION_PATTERNS = [
    "air pollution",
    "air contaminants",
    "ambient air pollution",
    "traffic related pollution",
    "traffic-related pollution",
    "traffic related air pollution",
    "traffic-related air pollution",
    "road proximity",
    "roadway proximity",
    "black smoke",
    "black carbon",
    "elemental carbon",
    "diesel exhaust",
    "vehicle exhaust",
    "traffic exhaust",
    "exhaust",
    "industrial pollution",
    "occupational particulate",
    "welding fumes",
    "welding fume",
    "wildfire smoke",
    "smoke events",
    "wood smoke",
    "biomass smoke",
    "biomass fuels",
    "biomass fuels wood crop residues dung",
    "environmental tobacco smoke",
    "secondhand smoke",
    "second hand smoke",
    "passive smoking",
    "ets",
    "shs",
    "cotinine",
    "serum cotinine",
    "urinary cotinine",
    "benzene",
    "polycyclic aromatic hydrocarbons",
    "pahs",
    "pah",
    "sulfate",
    "nitrate",
    "vanadium",
    "particle number",
    "particle number concentration",
    "particle number concentrations",
    "particles/cm",
    "nc0.02",
    "nc0 02",
    "ufp aviation",
    "h2s",
    "hydrogen sulfide",
    "tsp",
    "total suspended particulates",
    "spm",
    "suspended particulate matter",
    "bs",
    "bc",
    "organic carbon",
    "elemental carbon",
    "concentrated ambient particles",
    "fine caps",
    "coarse caps",
    "pnc",
    "dust storms",
    "asian dust storms",
    "desert dust",
    "dust weather condition",
    "dusty days",
    "formaldehyde",
    "hcho",
    "incense smoke",
    "cook smoke",
    "cooking smoke",
    "biomass fuel use",
    "biomass burning",
    "kerosene",
    "gas residential cooking fuel",
    "residential cooking fuel",
    "solid fuels",
    "solid fuels biomass",
    "mosquito coils",
    "iapcc",
    "indoor air pollution from coal combustion",
    "combustion products",
    "coal-fired power plant",
    "coal fired power plant",
    "power plant emissions",
    "methane emissions",
    "traffic intensity",
    "traffic intensity on nearest road",
    "traffic volume",
    "length of all roads",
    "length of local roads",
    "road length",
    "trucks passing near homes",
    "pmcoarse",
    "pm coarse",
    "rec",
    "respirable elemental carbon",
    "respirable dust",
    "inorganic dust",
    "occupational dust exposure",
    "occupational dust",
    "cotton dust",
    "diesel tractor use",
    "emissions from incinerators",
    "oil and gas wells",
    "oil gas wells",
    "complex source zone pollution",
    "limited local dispersion days",
    "air mass origin",
    "sulfur",
    "manganese",
    "high-sulfur fuel combustion",
    "high sulfur fuel combustion",
    "secondary organics",
]

CONTEXTUAL_AIR_POLLUTION_COMPACT_PATTERNS = {
    "airpollution",
    "aircontaminants",
    "ambientairpollution",
    "trafficrelatedpollution",
    "trafficrelatedairpollution",
    "roadproximity",
    "roadwayproximity",
    "blacksmoke",
    "blackcarbon",
    "elementalcarbon",
    "dieselexhaust",
    "vehicleexhaust",
    "trafficexhaust",
    "exhaust",
    "industrialpollution",
    "occupationalparticulate",
    "occupationalparticulateexposure",
    "weldingfumes",
    "weldingfume",
    "wildfiresmoke",
    "smokeevents",
    "woodsmoke",
    "biomasssmoke",
    "biomassfuels",
    "environmentaltobaccosmoke",
    "environmentaltobaccosmokeets",
    "secondhandsmoke",
    "secondhandsmokeshs",
    "passivesmoking",
    "ets",
    "shs",
    "cotinine",
    "serumcotinine",
    "urinarycotinine",
    "benzene",
    "polycyclicaromatichydrocarbons",
    "pahs",
    "pah",
    "sulfate",
    "nitrate",
    "vanadium",
    "particlenumber",
    "particlenumberconcentration",
    "particlenumberconcentrations",
    "particlescm",
    "nc002",
    "nc0021",
    "ufpaviation",
    "h2s",
    "hydrogensulfide",
    "tsp",
    "totalsuspendedparticulates",
    "spm",
    "suspendedparticulatematter",
    "bs",
    "bc",
    "organiccarbon",
    "elementalcarbon",
    "concentratedambientparticles",
    "finecaps",
    "coarsecaps",
    "pnc",
    "duststorms",
    "asianduststorms",
    "desertdust",
    "dustweathercondition",
    "dustydays",
    "formaldehyde",
    "hcho",
    "incensesmoke",
    "cooksmoke",
    "cookingsmoke",
    "biomassfueluse",
    "biomassburning",
    "kerosene",
    "gasresidentialcookingfuel",
    "residentialcookingfuel",
    "solidfuels",
    "solidfuelsbiomass",
    "mosquitocoils",
    "iapcc",
    "indoorairpollutionfromcoalcombustion",
    "combustionproducts",
    "coalfiredpowerplant",
    "coalfiredpowerplants",
    "powerplantemissions",
    "methaneemissions",
    "trafficintensity",
    "trafficintensityonnearestroad",
    "trafficvolume",
    "lengthofallroads",
    "lengthoflocalroads",
    "roadlength",
    "truckspassingnearhomes",
    "pmcoarse",
    "rec",
    "respirableelementalcarbon",
    "respirabledust",
    "inorganicdust",
    "occupationaldustexposure",
    "occupationaldust",
    "cottondust",
    "dieseltractoruse",
    "emissionsfromincinerators",
    "oilandgaswells",
    "oilgaswells",
    "complexsourcezonepollution",
    "limitedlocaldispersiondays",
    "airmassorigin",
    "sulfur",
    "manganese",
    "highsulfurfuelcombustion",
    "secondaryorganics",
}

REJECT_EXPOSURE_PATTERNS = [
    "mold",
    "fungi",
    "fungus",
    "cat allergen",
    "dog allergen",
    "cockroach allergen",
    "cockroaches",
    "cockroach",
    "bla g 1",
    "child-care",
    "child care",
    "day care",
    "day-care",
    "sharing a bedroom",
    "bedroom sharing",
    "male sex",
    "female sex",
    "temperature",
    "ambient temperature",
    "herbicide",
    "herbicides",
    "pesticide",
    "pesticides",
    "metolachlor",
    "pendimethalin",
    "chlorpyrifos",
    "diazinon",
    "farm crops",
    "farm animals",
    "farm dust",
    "house dust-derived beta-glucan",
    "house dust derived beta glucan",
    "acrylamide",
    "bde-153",
    "bde 153",
    "polybrominated diphenyl ether",
    "carbon dioxide",
    "co2",
    "co₂",
    "cockroaches",
    "cockroach",
    "cat ownership",
    "dog ownership",
    "doctor-diagnosed allergies",
    "doctor diagnosed allergies",
    "personal history of hay fever",
    "family history of atopy",
    "bedroom bed dust",
    "upholstery dust",
    "household dust index",
    "municipal water",
    "nonmunicipal water",
    "chlorination disinfection by-products",
    "chlorination disinfection by products",
    "cdbps",
    "persistent organic pollutants",
    "pops",
    "other types of wastes",
    "hazardous waste",
    "asbestos",
    "chlorinated solvents",
    "trichloroethylene",
    "vinyl chloride",
    "cadmium",
    "mercury",
    "lead",
    "blood lead",
    "blood lead concentration",
    "blood lead levels",
    "glycidamide",
    "glycidamide adducts",
    "infectious mononucleosis",
    "current wheeze proxy",
    "asthma medication use",
    "physical activity",
    "no flush toilet",
    "older age",
    "age",
    "day-of-week",
    "day of week",
    "monday",
    "c3c",
    "hay fever",
    "atopy",
    "smoking",
    "current smoking",
    "former smoking",
    "active smoking",
    "traditional cigarette",
    "cigarette smoke",
    "maternal cigarette smoke",
    "maternal smoking",
    "maternal smoking during pregnancy",
    "prenatal tobacco",
    "prenatal exposure to maternal cigarette smoking",
    "pemcs",
    "in utero tobacco smoke exposure",
    "tobacco smoking",
    "e-cigarette",
    "active e-cigarette smoking",
    "passive e-cigarette smoking",
    "tobacco cigarette smoking",
    "nnal",
    "nicotine",
    "air nicotine",
    "meconium nic",
    "il6 rs2069832",
    "decreased tlr4 methylation",
    "decreased alu methylation",
    "foxp3 promoter",
    "methylation",
    "control medical air",
    "control (medical air)",
    "hiv",
    "fried food consumption",
    "coffee consumption",
    "physical activity",
    "farm worker",
    "digging",
    "mowing",
    "planting",
    "fish consumption",
    "hormone replacement therapy",
    "recurrent urinary tract infections",
    "employment in high-risk occupations",
    "employment in high risk occupations",
    "nonmalignant respiratory disease",
    "lung mass",
    "fetal vascular thrombosis",
    "ftv",
    "cord blood ft4",
    "cord blood ft3",
    "cord blood tsh",
    "solar radiation",
    "sodium",
    "ndvi",
    "endotoxin",
    "occupational endotoxin exposure",
    "alternaria sensitization",
    "penicillium sensitization",
    "cladosporium sensitization",
    "dehp",
    "bbzp",
    "dep",
    "diethyl phthalate",
    "dibutyl phthalate",
    "butylbenzyl phthalate",
    "di(2-ethylhexyl) phthalate",
    "vinyl flooring",
    "snuff use",
    "fried food",
    "coffee",
    "food consumption",
    "fat intake",
]

REJECT_EXPOSURE_COMPACT_PATTERNS = {
    "mold",
    "fungi",
    "fungus",
    "catallergen",
    "dogallergen",
    "cockroachallergen",
    "cockroaches",
    "cockroach",
    "blag1",
    "childcare",
    "daycare",
    "sharingabedroom",
    "bedroomsharing",
    "malesex",
    "femalesex",
    "temperature",
    "ambienttemperature",
    "herbicide",
    "herbicides",
    "pesticide",
    "pesticides",
    "metolachlor",
    "pendimethalin",
    "chlorpyrifos",
    "diazinon",
    "farmcrops",
    "farmanimals",
    "farmdust",
    "housedustderivedbetaglucan",
    "acrylamide",
    "bde153",
    "polybrominateddiphenylether",
    "carbondioxide",
    "co2",
    "catownership",
    "dogownership",
    "doctordiagnosedallergies",
    "personalhistoryofhayfever",
    "familyhistoryofatopy",
    "bedroombeddust",
    "upholsterydust",
    "householddustindex",
    "municipalwater",
    "nonmunicipalwater",
    "chlorinationdisinfectionbyproducts",
    "cdbps",
    "persistentorganicpollutants",
    "pops",
    "othertypesofwastes",
    "hazardouswaste",
    "asbestos",
    "chlorinatedsolvents",
    "trichloroethylene",
    "vinylchloride",
    "cadmium",
    "mercury",
    "lead",
    "bloodlead",
    "bloodleadconcentration",
    "bloodleadlevels",
    "glycidamide",
    "glycidamideadducts",
    "infectiousmononucleosis",
    "currentwheezeproxy",
    "asthmamedicationuse",
    "physicalactivity",
    "noflushtoilet",
    "olderage",
    "age",
    "dayofweek",
    "monday",
    "c3c",
    "hayfever",
    "atopy",
    "smoking",
    "currentsmoking",
    "formersmoking",
    "activesmoking",
    "traditionalcigarette",
    "cigarettesmoke",
    "maternalcigarettesmoke",
    "maternalsmoking",
    "maternalsmokingduringpregnancy",
    "prenataltobacco",
    "prenatalexposuretomaternalcigarettesmoking",
    "pemcs",
    "inuterotobaccosmokeexposure",
    "tobaccosmoking",
    "ecigarette",
    "activeecigarettesmoking",
    "passiveecigarettesmoking",
    "tobaccocigarettesmoking",
    "nnal",
    "nicotine",
    "airnicotine",
    "meconiumnic",
    "il6rs2069832",
    "decreasedtlr4methylation",
    "decreasedalumethylation",
    "foxp3promoter",
    "methylation",
    "controlmedicalair",
    "hiv",
    "friedfoodconsumption",
    "coffeeconsumption",
    "physicalactivity",
    "farmworker",
    "digging",
    "mowing",
    "planting",
    "fishconsumption",
    "hormonereplacementtherapy",
    "recurrenturinarytractinfections",
    "employmentinhighriskoccupations",
    "nonmalignantrespiratorydisease",
    "lungmass",
    "fetalvascularthrombosis",
    "ftv",
    "cordbloodft4",
    "cordbloodft3",
    "cordbloodtsh",
    "solarradiation",
    "sodium",
    "ndvi",
    "endotoxin",
    "occupationalendotoxinexposure",
    "alternariasensitization",
    "penicilliumsensitization",
    "cladosporiumsensitization",
    "dehp",
    "bbzp",
    "dep",
    "diethylphthalate",
    "dibutylphthalate",
    "butylbenzylphthalate",
    "di2ethylhexylphthalate",
    "vinylflooring",
    "snuffuse",
    "friedfood",
    "coffee",
    "foodconsumption",
    "fatintake",
}


# Helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_float_or_none(value: Any) -> float | None:
    text = safe_str(value)

    if not text:
        return None

    text = text.replace(",", ".")
    text = text.replace("−", "-")
    text = re.sub(r"[^0-9eE\.\-\+]", "", text)

    if not text:
        return None

    try:
        return float(text)
    except Exception:
        return None


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    text = text.replace("<sub>2</sub>", "2")
    text = text.replace("<sub>3</sub>", "3")
    text = text.replace("<sub>x</sub>", "x")
    text = text.replace("<sub>X</sub>", "x")
    text = text.replace("μ", "µ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = " ".join(text.split())
    return text


def compact(value: Any) -> str:
    text = normalize_text(value)
    return re.sub(r"[^a-z0-9µ]", "", text)


def contains_word(text: str, word: str) -> bool:
    pattern = r"\b" + re.escape(word) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def contains_any_phrase(text: str, patterns: list[str] | set[str]) -> bool:
    normalized_text = normalize_text(text)

    for pattern in patterns:
        normalized_pattern = normalize_text(pattern)
        if normalized_pattern and normalized_pattern in normalized_text:
            return True

    return False


def contains_any_compact(text: str, patterns: list[str] | set[str]) -> bool:
    compact_text = compact(text)

    for pattern in patterns:
        compact_pattern = compact(pattern)
        if compact_pattern and compact_pattern in compact_text:
            return True

    return False


def is_missing_or_generic_pollutant(
    pollutant_general: Any,
    pollutant_specific: Any,
    pollutant_original: Any,
) -> bool:
    values = [
        compact(pollutant_general),
        compact(pollutant_specific),
        compact(pollutant_original),
    ]

    generic_values = {
        "",
        "nan",
        "none",
        "null",
        "other",
        "unknown",
        "ambiguous",
        "notreported",
    }

    return all(value in generic_values for value in values)


# QC classification

def classify_measure(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    measure_type = normalize_text(row.get("measure_type"))
    measure_name = normalize_text(row.get("measure_name"))
    measure_role = normalize_text(row.get("measure_role"))
    evidence = normalize_text(row.get("evidence_sentence"))

    effect_value = parse_float_or_none(row.get("effect_value"))
    ci_lower = parse_float_or_none(row.get("ci_lower"))
    ci_upper = parse_float_or_none(row.get("ci_upper"))
    p_value = safe_str(row.get("p_value"))
    statistical_significance = normalize_text(row.get("statistical_significance"))

    text = " ".join([measure_type, measure_name, measure_role, evidence])

    if (
        measure_type in {"p value", "pvalue", "p"}
        or "p value for trend" in text
        or "test for trend" in text
        or "tests for trend" in text
    ):
        reasons.append("p_value_or_trend_test_not_direct_effect_size")
        return "reject_measure", reasons

    if measure_role in {
        "heterogeneity test",
        "pleiotropy test",
        "gene association",
        "model diagnostic",
        "incomplete effect description",
    }:
        reasons.append(f"measure_role_not_direct_effect: {measure_role}")
        return "reject_measure", reasons

    valid_effect_types = {
        "or",
        "rr",
        "hr",
        "irr",
        "beta",
        "coefficient",
        "percent change",
        "percent_change",
    }

    if measure_type not in valid_effect_types:
        reasons.append(f"unsupported_measure_type: {measure_type}")
        return "reject_measure", reasons

    if effect_value is None:
        reasons.append("missing_numeric_effect_value")
        return "reject_measure", reasons

    has_ci = ci_lower is not None and ci_upper is not None
    has_p = bool(p_value)

    exposure_increment_text = safe_str(row.get("exposure_increment"))
    evidence_text = safe_str(row.get("evidence_sentence")).lower()

    has_explicit_increment = (
        bool(exposure_increment_text)
        or "per " in evidence_text
        or "for every" in evidence_text
        or "increase in" in evidence_text
        or "decrease in" in evidence_text
        or "associated with" in evidence_text
        or "compared with" in evidence_text
        or "vs." in evidence_text
        or " versus " in evidence_text
    )

    has_se = (
        "se=" in evidence_text
        or "se =" in evidence_text
        or "(se" in evidence_text
        or "standard error" in evidence_text
    )

    has_direct_association_text = (
        "associated with" in evidence_text
        or "association between" in evidence_text
        or "increased risk" in evidence_text
        or "decreased risk" in evidence_text
        or "increase in" in evidence_text
        or "decrease in" in evidence_text
        or "higher risk" in evidence_text
        or "lower risk" in evidence_text
        or "significant" in evidence_text
        or "non-significant" in evidence_text
        or "non significant" in evidence_text
    )

    if measure_type in {"percent change", "percent_change"}:
        if has_explicit_increment:
            reasons.append("valid_percent_change_effect_estimate_without_ci_or_p")
            return "valid_measure", reasons

    if not has_ci and not has_p:
        has_significance_label = statistical_significance in {
            "significant",
            "non significant",
            "non_significant",
            "unknown",
        }

        if (
            measure_role == "direct effect estimate"
            and measure_type in valid_effect_types
            and (
                has_se
                or has_explicit_increment
                or has_direct_association_text
                or has_significance_label
            )
        ):
            reasons.append("valid_direct_effect_estimate_without_ci_or_p")
            return "valid_measure", reasons

        reasons.append("missing_ci_and_p_value")
        return "review_measure", reasons

    return "valid_measure", reasons


def classify_exposure(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    pollutant_general = row.get("pollutant_general")
    pollutant_specific = row.get("pollutant_specific")
    pollutant_original = row.get("pollutant_original_mention")
    pollutant_role = normalize_text(row.get("pollutant_role"))
    exposure_increment = row.get("exposure_increment")
    evidence_sentence = row.get("evidence_sentence")

    pollutant_text = normalize_text(
        " ".join(
            [
                safe_str(pollutant_general),
                safe_str(pollutant_specific),
                safe_str(pollutant_original),
            ]
        )
    )

    exposure_text = normalize_text(
        " ".join(
            [
                safe_str(pollutant_general),
                safe_str(pollutant_specific),
                safe_str(pollutant_original),
                safe_str(exposure_increment),
            ]
        )
    )

    evidence_text = normalize_text(evidence_sentence)

    source_text = normalize_text(" ".join([pollutant_text, exposure_text]))
    combined_text = normalize_text(" ".join([source_text, evidence_text]))

    key_specific = compact(pollutant_specific)
    key_general = compact(pollutant_general)
    key_original = compact(pollutant_original)

    if is_missing_or_generic_pollutant(
        pollutant_general=pollutant_general,
        pollutant_specific=pollutant_specific,
        pollutant_original=pollutant_original,
    ):
        if contains_any_phrase(evidence_text, COVARIATE_EXPOSURE_TERMS):
            reasons.append("covariate_or_non_pollutant_effect")
            return "reject_exposure", reasons

        if contains_any_phrase(evidence_text, NON_AIR_POLLUTION_TERMS):
            reasons.append("non_air_pollution_exposure")
            return "reject_exposure", reasons

        reasons.append("missing_or_generic_pollutant")
        return "reject_exposure", reasons

    # Tobacco:
    # Keep passive/environmental tobacco smoke as contextual air pollution.
    # Reject active/current/former/prenatal/maternal/e-cigarette and smoking
    # biomarker/genetic proxies as non-air-pollution exposures.
    active_or_prenatal_tobacco_patterns = [
        "active smoking",
        "current smoking",
        "former smoking",
        "personal smoking",
        "traditional cigarette",
        "cigarette smoke",
        "tobacco cigarette smoking",
        "active e-cigarette smoking",
        "passive e-cigarette smoking",
        "e-cigarette",
        "maternal cigarette smoke",
        "maternal smoking",
        "maternal smoking during pregnancy",
        "prenatal tobacco",
        "prenatal exposure to maternal cigarette smoking",
        "pemcs",
        "in utero tobacco smoke exposure",
        "in utero tobacco",
        "smoking continued during pregnancy",
        "smoking stopped before pregnancy",
        "paternal smoking",
        "smoking by all family members",
        "nnal",
        "nicotine",
        "air nicotine",
        "meconium nic",
        "smoking cg",
        "cg05575921",
        "cg06126421",
        "cg23576855",
        "cg06644428",
    ]

    if contains_any_phrase(source_text, active_or_prenatal_tobacco_patterns):
        reasons.append("non_air_pollution_active_or_prenatal_tobacco")
        return "reject_exposure", reasons

    passive_tobacco_patterns = [
        "environmental tobacco smoke",
        "secondhand smoke",
        "second hand smoke",
        "passive smoking",
        "passive tobacco",
        "passive cigarette",
        "household tobacco smoke",
        "household exposure to tobacco smoke",
        "tobacco smoke exposure",
        "smoke in the environment",
    ]

    if (
        contains_any_phrase(source_text, passive_tobacco_patterns)
        or contains_any_phrase(combined_text, passive_tobacco_patterns)
        or ("tobacco smoke" in source_text and "household" in source_text)
    ):
        reasons.append("contextual_air_pollution_passive_tobacco_smoke")
        return "contextual_air_pollutant", reasons

    # Strong explicit rejection rules are evaluated before textual
    # air-pollution fallback rules.
    if (
        contains_any_phrase(source_text, REJECT_EXPOSURE_PATTERNS)
        or contains_any_compact(source_text, REJECT_EXPOSURE_COMPACT_PATTERNS)
    ):
        if not (
            contains_any_phrase(source_text, CONTEXTUAL_AIR_POLLUTION_PATTERNS)
            or contains_any_compact(source_text, CONTEXTUAL_AIR_POLLUTION_COMPACT_PATTERNS)
        ):
            if contains_any_phrase(source_text, COVARIATE_EXPOSURE_TERMS):
                reasons.append("covariate_or_non_pollutant_effect")
                return "reject_exposure", reasons

            reasons.append("non_air_pollution_exposure")
            return "reject_exposure", reasons

    if key_specific in PROJECT_TARGET_KEYS or key_general in PROJECT_TARGET_KEYS:
        return "project_target_air_pollutant", reasons

    if (
        key_specific in CONTEXTUAL_AIR_POLLUTANT_KEYS
        or key_general in CONTEXTUAL_AIR_POLLUTANT_KEYS
        or key_original in CONTEXTUAL_AIR_POLLUTANT_KEYS
    ):
        return "contextual_air_pollutant", reasons

    if (
        contains_any_phrase(source_text, TARGET_AIR_POLLUTION_PATTERNS)
        or contains_any_compact(source_text, TARGET_AIR_POLLUTION_COMPACT_PATTERNS)
    ):
        reasons.append("project_target_air_pollutant_text_pattern")
        return "project_target_air_pollutant", reasons

    if pollutant_role == "source marker":
        reasons.append("air_pollution_source_marker")
        return "source_marker_air_pollution", reasons

    road_traffic_proxy_terms = [
        "length of all roads",
        "length of local roads",
        "road length",
        "traffic intensity",
        "traffic intensity on nearest road",
        "traffic volume",
        "trucks passing near homes",
        "trucks near homes",
        "nearest road",
        "local roads",
        "road buffer",
        "50 m buffer",
        "100 m buffer",
        "200 m buffer",
    ]

    if (
        "traffic related" in pollutant_text
        or "traffic related" in exposure_text
        or "road proximity" in pollutant_text
        or "road proximity" in exposure_text
        or contains_word(pollutant_text, "trp")
        or contains_word(exposure_text, "trp")
        or contains_any_phrase(source_text, road_traffic_proxy_terms)
    ):
        reasons.append("traffic_related_source_marker")
        return "source_marker_air_pollution", reasons

    source_marker_patterns = [
        "limited local dispersion days",
        "air mass origin",
        "traffic volume",
        "traffic intensity",
        "diesel tractor use",
        "coal-fired power plant",
        "coal fired power plant",
        "power plant",
        "oil and gas wells",
        "emissions from incinerators",
        "complex source zone pollution",
    ]

    if contains_any_phrase(source_text, source_marker_patterns):
        reasons.append("air_pollution_source_marker_text_pattern")
        return "source_marker_air_pollution", reasons

    if "h2s" in exposure_text or "hydrogen sulfide" in exposure_text:
        reasons.append("contextual_air_pollutant_h2s")
        return "contextual_air_pollutant", reasons

    if (
        contains_any_phrase(source_text, CONTEXTUAL_AIR_POLLUTION_PATTERNS)
        or contains_any_compact(source_text, CONTEXTUAL_AIR_POLLUTION_COMPACT_PATTERNS)
    ):
        reasons.append("contextual_air_pollution_text_pattern")
        return "contextual_air_pollutant", reasons

    if contains_any_phrase(exposure_text, NON_AIR_POLLUTION_TERMS):
        reasons.append("non_air_pollution_exposure")
        return "reject_exposure", reasons

    if contains_any_phrase(exposure_text, COVARIATE_EXPOSURE_TERMS):
        reasons.append("covariate_or_non_pollutant_effect")
        return "reject_exposure", reasons

    if (
        contains_any_phrase(combined_text, TARGET_AIR_POLLUTION_PATTERNS)
        or contains_any_compact(combined_text, TARGET_AIR_POLLUTION_COMPACT_PATTERNS)
    ):
        reasons.append("project_target_air_pollutant_evidence_pattern")
        return "project_target_air_pollutant", reasons

    if (
        contains_any_phrase(combined_text, CONTEXTUAL_AIR_POLLUTION_PATTERNS)
        or contains_any_compact(combined_text, CONTEXTUAL_AIR_POLLUTION_COMPACT_PATTERNS)
    ):
        reasons.append("contextual_air_pollution_evidence_pattern")
        return "contextual_air_pollutant", reasons

    metal_terms = {
        "nickel",
        "iron",
        "zinc",
        "vanadium",
        "manganese",
        "copper",
        "sulfur",
        "silicon",
        "calcium",
        "chromium",
        "tin",
        "heavy metals",
        "metals",
    }

    air_context_terms = [
        "air levels",
        "air level",
        "air concentration",
        "air concentrations",
        "airborne",
        "ambient",
        "ng/m3",
        "ng/m³",
        "µg/m3",
        "µg/m³",
        "ug/m3",
        "particulate",
        "particles",
        "pm",
        "truck drivers",
        "emissions",
        "traffic",
        "industrial",
        "combustion",
        "pollution",
    ]

    if contains_any_phrase(source_text, metal_terms):
        if contains_any_phrase(combined_text, air_context_terms):
            reasons.append("contextual_air_pollution_metal_air_context")
            return "contextual_air_pollutant", reasons

        reasons.append("non_air_pollution_exposure")
        return "reject_exposure", reasons

    # Evidence-level non-air-pollution cleanup for rows whose source mention is
    # vague (for example "air contaminants") but the evidence sentence shows an
    # allergen/fungi/covariate exposure.
    evidence_reject_terms = {
        "fungi",
        "fungus",
        "mold",
        "allergen",
        "cockroach",
        "alternaria",
        "penicillium",
        "cladosporium",
        "hay fever",
        "atopy",
        "hiv",
        "methylation",
        "genotype",
        "high-risk occupations",
        "nonmalignant respiratory disease",
        "food consumption",
        "coffee consumption",
        "fried food",
        "fish consumption",
        "hormone replacement therapy",
        "urinary tract infections",
    }

    if contains_any_phrase(combined_text, evidence_reject_terms):
        reasons.append("non_air_pollution_exposure")
        return "reject_exposure", reasons

    reasons.append("ambiguous_or_non_target_exposure")
    return "review_exposure", reasons


def infer_human_study_from_row(row: dict[str, Any]) -> bool:
    combined = normalize_text(
        " ".join(
            [
                safe_str(row.get("outcome_core")),
                safe_str(row.get("outcome_normalized")),
                safe_str(row.get("outcome_category")),
                safe_str(row.get("population_group")),
                safe_str(row.get("evidence_sentence")),
                safe_str(row.get("source_section")),
            ]
        )
    )

    non_human_word_terms = [
        "mice",
        "mouse",
        "rat",
        "rats",
        "murine",
        "zebrafish",
    ]

    non_human_phrase_terms = [
        "cell line",
        "in vitro",
        "animal model",
    ]

    human_word_terms = [
        "patients",
        "patient",
        "children",
        "child",
        "adults",
        "adult",
        "females",
        "female",
        "males",
        "male",
        "women",
        "men",
        "subjects",
        "participants",
    ]

    human_phrase_terms = [
        "pregnant women",
        "study subjects",
        "hospital admission",
        "daily dispensing",
        "dispensing of glyceryl trinitrates",
        "asthma",
        "acute angina",
        "angina pectoris",
        "alzheimer",
        "vascular dementia",
        "acute kidney injury",
        "amyotrophic lateral sclerosis",
        "lung cancer",
        "adenocarcinoma",
        "spontaneous abortion",
    ]

    if any(contains_word(combined, term) for term in non_human_word_terms):
        return False

    if any(term in combined for term in non_human_phrase_terms):
        return False

    if any(contains_word(combined, term) for term in human_word_terms):
        return True

    if any(term in combined for term in human_phrase_terms):
        return True

    return safe_bool(row.get("is_human_study"))


def classify_outcome(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    outcome_core = normalize_text(row.get("outcome_core"))
    outcome_role = normalize_text(row.get("outcome_role"))
    is_human = infer_human_study_from_row(row)

    if not outcome_core:
        reasons.append("missing_outcome_core")
        return "reject_outcome", reasons

    if not is_human:
        reasons.append("non_human_study_or_unknown_human_status")
        return "reject_outcome", reasons

    if outcome_role == "case definition component":
        reasons.append("case_definition_component_not_final_outcome")
        return "reject_outcome", reasons

    return "valid_outcome", reasons


def classify_result_context(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    source_section = normalize_text(row.get("source_section"))
    exposure_increment = normalize_text(row.get("exposure_increment"))
    evidence = normalize_text(row.get("evidence_sentence"))

    combined = " ".join([source_section, exposure_increment, evidence])

    if "sensitivity" in combined or "excluding prevalent cases" in combined:
        reasons.append("sensitivity_analysis_detected")
        return "sensitivity_analysis", reasons

    if "concentration response" in combined or "concentration-response" in combined:
        reasons.append("concentration_response_detected")
        return "concentration_response", reasons

    if (
        "table s" in combined
        or "supplement" in combined
        or "supplementary" in combined
    ):
        reasons.append("supplementary_result_detected")
        return "supplementary_analysis", reasons

    subgroup_terms_phrase = [
        "non smokers",
        "non-smokers",
        "low pollution cohort",
        "high parental stress",
        "low parental stress",
        "apoe",
        "carriers",
        "noncarriers",
        "midwest",
        "northeast",
        "region",
    ]

    subgroup_terms_word = [
        "men",
        "women",
        "male",
        "female",
        "smokers",
    ]

    if any(term in combined for term in subgroup_terms_phrase):
        reasons.append("subgroup_analysis_detected")
        return "subgroup_analysis", reasons

    if any(contains_word(combined, term) for term in subgroup_terms_word):
        reasons.append("subgroup_analysis_detected")
        return "subgroup_analysis", reasons

    return "main_result", reasons


def make_qc_decision(row: dict[str, Any]) -> dict[str, Any]:
    measure_status, measure_reasons = classify_measure(row)
    exposure_status, exposure_reasons = classify_exposure(row)
    outcome_status, outcome_reasons = classify_outcome(row)
    result_context, context_reasons = classify_result_context(row)

    reasons = measure_reasons + exposure_reasons + outcome_reasons + context_reasons

    is_project_target = safe_bool(row.get("is_project_target"))
    original_main = safe_bool(row.get("include_in_main_project_analysis"))

    reject = (
        measure_status == "reject_measure"
        or exposure_status == "reject_exposure"
        or outcome_status == "reject_outcome"
    )

    review = (
        measure_status == "review_measure"
        or exposure_status == "review_exposure"
    )

    if reject:
        qc_decision = "reject"
    elif review:
        qc_decision = "review"
    else:
        qc_decision = "accept"

    include_in_clean_database = qc_decision in {"accept", "review"}

    include_in_clean_main_analysis = (
        qc_decision == "accept"
        and is_project_target
        and original_main
        and result_context in {
            "main_result",
            "subgroup_analysis",
            "sensitivity_analysis",
            "supplementary_analysis",
            "concentration_response",
        }
    )

    if result_context != "main_result":
        reasons.append(f"result_context={result_context}")

    if include_in_clean_main_analysis:
        clean_role = "main_project_clean_association"
    elif include_in_clean_database and exposure_status in {
        "contextual_air_pollutant",
        "source_marker_air_pollution",
    }:
        clean_role = "contextual_air_pollution_association"
    elif include_in_clean_database and exposure_status == "project_target_air_pollutant":
        clean_role = "target_pollutant_secondary_or_review_association"
    elif include_in_clean_database:
        clean_role = "review_association"
    else:
        clean_role = "rejected_association"

    return {
        "qc_decision": qc_decision,
        "qc_role": clean_role,
        "qc_measure_status": measure_status,
        "qc_exposure_status": exposure_status,
        "qc_outcome_status": outcome_status,
        "qc_result_context": result_context,
        "qc_include_in_clean_database": include_in_clean_database,
        "qc_include_in_clean_main_analysis": include_in_clean_main_analysis,
        "qc_reasons": " | ".join(reasons),
    }


def apply_qc(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clean_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []

    for row in rows:
        qc = make_qc_decision(row)
        enriched = {**row, **qc}

        if qc["qc_decision"] in {"accept", "review"}:
            clean_rows.append(enriched)
        else:
            rejected_rows.append(enriched)

    return clean_rows, rejected_rows


# Audit

def build_audit(
    input_rows: list[dict[str, Any]],
    clean_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    all_rows = clean_rows + rejected_rows

    by_decision = Counter(row.get("qc_decision", "") for row in all_rows)
    by_role = Counter(row.get("qc_role", "") for row in all_rows)
    by_result_context = Counter(row.get("qc_result_context", "") for row in all_rows)
    by_exposure_status = Counter(row.get("qc_exposure_status", "") for row in all_rows)
    by_measure_status = Counter(row.get("qc_measure_status", "") for row in all_rows)
    by_outcome_status = Counter(row.get("qc_outcome_status", "") for row in all_rows)

    by_pmid = defaultdict(
        lambda: {
            "input_rows": 0,
            "clean_rows": 0,
            "rejected_rows": 0,
            "clean_main": 0,
            "review_rows": 0,
        }
    )

    for row in input_rows:
        pmid = safe_str(row.get("pmid"))
        by_pmid[pmid]["input_rows"] += 1

    for row in clean_rows:
        pmid = safe_str(row.get("pmid"))
        by_pmid[pmid]["clean_rows"] += 1

        if safe_bool(row.get("qc_include_in_clean_main_analysis")):
            by_pmid[pmid]["clean_main"] += 1

        if row.get("qc_decision") == "review":
            by_pmid[pmid]["review_rows"] += 1

    for row in rejected_rows:
        pmid = safe_str(row.get("pmid"))
        by_pmid[pmid]["rejected_rows"] += 1

    return {
        "run_date": now_iso(),
        "totals": {
            "input_rows": len(input_rows),
            "clean_rows": len(clean_rows),
            "rejected_rows": len(rejected_rows),
            "clean_main_analysis_rows": sum(
                safe_bool(row.get("qc_include_in_clean_main_analysis"))
                for row in clean_rows
            ),
            "review_rows": sum(row.get("qc_decision") == "review" for row in clean_rows),
        },
        "by_decision": dict(by_decision),
        "by_role": dict(by_role),
        "by_result_context": dict(by_result_context),
        "by_exposure_status": dict(by_exposure_status),
        "by_measure_status": dict(by_measure_status),
        "by_outcome_status": dict(by_outcome_status),
        "by_pmid": dict(by_pmid),
    }


def write_audit_csv(path: Path, audit: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []

    rows.append({"metric": "input_rows", "value": audit["totals"]["input_rows"]})
    rows.append({"metric": "clean_rows", "value": audit["totals"]["clean_rows"]})
    rows.append({"metric": "rejected_rows", "value": audit["totals"]["rejected_rows"]})
    rows.append(
        {
            "metric": "clean_main_analysis_rows",
            "value": audit["totals"]["clean_main_analysis_rows"],
        }
    )
    rows.append({"metric": "review_rows", "value": audit["totals"]["review_rows"]})

    for key, value in audit.get("by_decision", {}).items():
        rows.append({"metric": f"decision.{key}", "value": value})

    for key, value in audit.get("by_role", {}).items():
        rows.append({"metric": f"role.{key}", "value": value})

    for key, value in audit.get("by_result_context", {}).items():
        rows.append({"metric": f"result_context.{key}", "value": value})

    for key, value in audit.get("by_exposure_status", {}).items():
        rows.append({"metric": f"exposure_status.{key}", "value": value})

    for key, value in audit.get("by_measure_status", {}).items():
        rows.append({"metric": f"measure_status.{key}", "value": value})

    for key, value in audit.get("by_outcome_status", {}).items():
        rows.append({"metric": f"outcome_status.{key}", "value": value})

    write_csv_rows(path, rows, fieldnames=AUDIT_COLUMNS)


# Public API

def run_final_quality_control(
    input_csv: Path,
    clean_csv: Path,
    rejected_csv: Path,
    audit_csv: Path,
    audit_json: Path,
) -> dict[str, Any]:
    input_rows = read_csv_rows(input_csv)

    if not input_rows:
        raise ValueError(f"Input CSV is empty: {input_csv}")

    clean_rows, rejected_rows = apply_qc(input_rows)

    original_columns = list(input_rows[0].keys())
    output_columns = original_columns + [
        col for col in QC_COLUMNS if col not in original_columns
    ]

    write_csv_rows(clean_csv, clean_rows, fieldnames=output_columns)
    write_csv_rows(rejected_csv, rejected_rows, fieldnames=output_columns)

    audit = build_audit(
        input_rows=input_rows,
        clean_rows=clean_rows,
        rejected_rows=rejected_rows,
    )

    audit["outputs"] = {
        "clean_csv": str(clean_csv),
        "rejected_csv": str(rejected_csv),
        "audit_csv": str(audit_csv),
        "audit_json": str(audit_json),
    }

    write_json(audit_json, audit)
    write_audit_csv(audit_csv, audit)

    return audit
