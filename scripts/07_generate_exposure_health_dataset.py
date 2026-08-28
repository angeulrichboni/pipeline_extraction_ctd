"""Chapitre 4 -- Construction du dataset exposition-sante.

REGLE DE METHODE NON NEGOCIABLE (fuite de cible) :
  link_label, association_strength et evidence_weight ne
  doivent JAMAIS etre utilises comme variables d'entree d'un modele
  predictif entraine sur ce fichier. Pour les lignes negatives
  (unknown_sampled_negative), ces quatre colonnes valent 0 PAR
  CONSTRUCTION -- un modele qui les recevrait en entree apprendrait a
  reconnaitre ce zero plutot qu'un vrai signal d'exposition. Elles
  restent dans le fichier uniquement comme metadonnees de tracabilite,
  poids d'arete, ou outil de classement exploratoire.

REGLE DE METHODE -- hypothese de monde ouvert :
  Une categorie ICD absente des associations CTD pour un polluant donne
  est etiquetee unknown_sampled_negative, jamais "negatif prouve".
  L'absence dans CTD peut signifier une absence reelle d'association,
  mais tout aussi bien une association non etudiee, un article absent
  de la base, ou une fenetre temporelle non documentee.

REGLE DE METHODE -- parite train/inference (composition de s) :
  individual_id et persona_id ne doivent jamais servir de variable
  d'entree du modele -- un futur cas reel n'a pas d'identite synthetique
  a fournir. Seules les colonnes classe_age, grossesse et
  pathologie_preexistante (Famille B, profil generalise) et les
  colonnes de trajectoire (Famille A, prefixees mean_/cumulative_/
  consecutive_/exposure_) constituent le sujet s exploitable par le
  modele. individual_id et persona_id restent dans le fichier pour la
  tracabilite et la reconstruction de sequences, pas comme features.
"""
from __future__ import annotations

import csv
import gzip
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable

from .io_utils import csv_writer, open_text_output

DATASET_COLUMNS = [
    "window_id", "individual_id", "persona_id", "household_id", "pollutant",
    "window_type", "window_start", "window_end", "year", "date",
    # Famille B -- profil generalise (parite train/inference)
    "classe_age", "grossesse", "pathologie_preexistante",
    # Famille A -- niveau courant de la fenetre
    "mean_exposure", "home_mean_exposure", "max_exposure", "sum_exposure",
    "valid_slots", "home_minutes", "mean_exceedance", "max_exceedance",
    "mil_exceedance", "proportion_above_threshold", "excess_mean",
    "excess_max", "excess_burden",
    # Famille A -- trajectoire longitudinale (chapitre 3, etage 2)
    "window_index", "cumulative_exposure", "cumulative_excess_burden",
    "consecutive_exceedances", "max_consecutive_exceedances_to_date",
    "exposure_slope_7j", "exposure_trend_direction",
    # Objet o et relation r
    "icd_chapter", "icd_chapter_name",
    # Etiquette et metadonnees de tracabilite -- jamais en feature (voir ci-dessus)
    # health_score retire : combinait 4 quantites via des poids non
    # rattaches a une source publiee ni a une calibration empirique
    # (cf. docs/PIPELINE.md, retrait documente). Les composants restent
    # disponibles separement (exposure_signal, association_strength,
    # evidence_weight, persona_relevance, p0_relevance) pour qui veut
    # recalculer un score composite explicite, a la demande.
    "link_label", "exposure_signal", "association_strength",
    "association_beta_mean", "effect_measure_count", "association_count",
    "pmid_count", "outcome_count", "evidence_weight", "window_evidence",
    "p0_event_ids", "p0_value_max", "p0_relevance", "persona_relevance",
]

MEASURE_ALIASES = {
    "or", "odds_ratio", "odds ratio",
    "rr", "risk_ratio", "risk ratio", "relative_risk", "relative risk",
    "hr", "hazard_ratio", "hazard ratio",
    "rate_ratio", "rate ratio",
}

EVENT_TO_CHAPTER = {
    "E02": "10",  # asthme -> X respiratoire
    "E03": "09",  # cardiopathie ischémique -> IX circulatoire
    "E04": "09",  # AVC / stroke -> IX circulatoire en ICD-10 (I60-I64), PAS
                  # VI nerveux : cas documenté dans config/icd10_chapter_correspondence.csv
                  # (ancien regroupement 08 "partial", 76,4% -> VI mais AVC -> IX
                  # circulatoire). Vérifié directement sur icd10_table_reference.csv :
                  # I60-I64 sont bien classés sous le chapitre IX (circulatoire).
    "E05": "16",  # prématurité -> XVI périnatal
    "E08": "15",  # pré-éclampsie -> XV grossesse
    # E06 (faible poids) et E07 (SGA) retirés : jamais émis par
    # p0_schedule.generate_p0_schedule() -- aucune règle p0 ne produit
    # ces event_id pour l'instant. Réintroduire ici seulement après
    # avoir ajouté leur génération dans p0_schedule.py.
}

PERSONA_RELEVANT_CHAPTERS = {
    "P1": {"10"},        # X respiratoire
    "P2": {"06", "09"},  # VI nerveux, IX circulatoire
    "P3": {"15", "16"},  # XV grossesse, XVI périnatal
    "P4": {"06", "09"},
    "P5": {"10"},
}


@dataclass
class AssociationBucket:
    pollutant: str
    window_type: str
    icd_chapter: str
    icd_chapter_name: str
    window_evidence: str
    association_ids: set[str]
    pmids: set[str]
    outcomes: set[str]
    betas: list[float]

    def add(self, row: dict[str, str], beta: float | None) -> None:
        assoc = row.get("association_id", "") or row.get("pmid", "") or row.get("outcome_normalized", "")
        if assoc:
            self.association_ids.add(assoc)
        pmid = row.get("pmid", "")
        if pmid:
            self.pmids.add(pmid)
        outcome = row.get("normalized_health_concept", "") or row.get("outcome_normalized", "")
        if outcome:
            self.outcomes.add(outcome)
        if beta is not None and math.isfinite(beta):
            self.betas.append(beta)

    @property
    def association_count(self) -> int:
        return len(self.association_ids)

    @property
    def pmid_count(self) -> int:
        return len(self.pmids)

    @property
    def outcome_count(self) -> int:
        return len(self.outcomes)

    @property
    def beta_mean(self) -> float:
        return sum(self.betas) / len(self.betas) if self.betas else 0.0

    @property
    def effect_measure_count(self) -> int:
        return len(self.betas)

    @property
    def evidence_weight(self) -> float:
        # 10 PMIDs ou plus donne un poids proche de 1 sans surpondérer les très gros chapitres.
        pmid_component = min(1.0, math.log1p(self.pmid_count) / math.log1p(10))
        outcome_component = min(1.0, math.log1p(self.outcome_count) / math.log1p(8))
        weight = 0.65 * pmid_component + 0.35 * outcome_component
        if self.window_evidence == "unspecified_window":
            weight *= 0.65
        return max(0.05, min(1.0, weight))

    @property
    def association_strength(self) -> float:
        if self.betas:
            # Force sur une augmentation de 10 µg/m3; une variation relative x2 est plafonnée à 1.
            strength = abs(self.beta_mean * 10.0) / math.log(2.0)
            return max(0.02, min(1.0, strength))
        # Association présente, mais sans OR/RR/HR exploitable.
        return 0.25 * self.evidence_weight


def open_text_input(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _require_columns(fieldnames: Iterable[str] | None, required: set[str], path: Path) -> None:
    available = set(fieldnames or [])
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"Colonnes manquantes dans {path}: {missing}")


def _normalize_pollutant(value: str) -> str | None:
    raw = (value or "").strip().upper().replace(" ", "")
    if raw in {"PM2.5", "PM25", "PM_2.5"}:
        return "PM25"
    if raw in {"PM10", "PM_10"}:
        return "PM10"
    return None


def _window_types(row: dict[str, str]) -> list[tuple[str, str]]:
    category = (row.get("exposure_window_category") or "").lower()
    duration = (row.get("exposure_duration_unit") or "").lower()
    if "short" in category or duration in {"hour", "hours", "day", "days"}:
        return [("daily", "direct_window")]
    if "long" in category or duration in {"month", "months", "year", "years", "annual"}:
        return [("annual", "direct_window")]
    return [("daily", "unspecified_window"), ("annual", "unspecified_window")]


def _effect_beta(row: dict[str, str]) -> float | None:
    measure = (row.get("measure_type") or "").strip().lower()
    value_text = row.get("effect_value_numeric") or ""
    increment_text = row.get("exposure_increment_value") or ""
    try:
        value = float(value_text)
    except ValueError:
        return None
    try:
        increment = float(increment_text)
    except ValueError:
        increment = 1.0
    if not math.isfinite(value) or value <= 0:
        return None
    if not math.isfinite(increment) or increment <= 0:
        increment = 1.0

    beta: float | None = None
    if measure in MEASURE_ALIASES:
        beta = math.log(value) / increment
    elif "odds" in measure or "risk" in measure or "hazard" in measure or "relative" in measure:
        beta = math.log(value) / increment
    elif "percent" in measure or "%" in measure:
        relative = 1.0 + value / 100.0
        if relative > 0:
            beta = math.log(relative) / increment
    if beta is None:
        return None

    direction = (row.get("effect_direction") or "").lower()
    if any(token in direction for token in ("decrease", "protect", "inverse", "negative")):
        beta = -abs(beta)
    return beta


CORE_ICD_CHAPTERS = {"06", "09", "10", "15", "16"}  # ICD-10 : VI nerveux, IX circulatoire, X respiratoire, XV grossesse, XVI périnatal


def build_association_summary(
    ctd_path: Path,
    *,
    allowed_chapters: set[str] | None = None,
) -> tuple[dict[tuple[str, str], dict[str, AssociationBucket]], dict[str, str]]:
    required = {
        "pollutant_specific", "pollutant_general", "mapping_status", "icd_chapter",
        "icd_chapter_name", "outcome_normalized", "measure_type",
        "effect_value_numeric", "exposure_increment_value",
        "exposure_window_category", "exposure_duration_unit",
    }
    buckets: dict[tuple[str, str, str], AssociationBucket] = {}
    all_chapters: dict[str, str] = {}

    with open_text_input(ctd_path) as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, required, ctd_path)
        for row in reader:
            if row.get("mapping_status") != "VALIDATED_ICD":
                continue
            pollutant = _normalize_pollutant(row.get("pollutant_specific") or "")
            if pollutant is None:
                pollutant = _normalize_pollutant(row.get("pollutant_general") or "")
            if pollutant is None:
                continue
            chapter = (row.get("icd_chapter") or "").strip()
            chapter_name = (row.get("icd_chapter_name") or "").strip()
            if not chapter or not chapter_name:
                continue
            if allowed_chapters is not None and chapter not in allowed_chapters:
                continue
            all_chapters[chapter] = chapter_name
            beta = _effect_beta(row)
            for window_type, window_evidence in _window_types(row):
                key = (pollutant, window_type, chapter)
                if key not in buckets:
                    buckets[key] = AssociationBucket(
                        pollutant=pollutant,
                        window_type=window_type,
                        icd_chapter=chapter,
                        icd_chapter_name=chapter_name,
                        window_evidence=window_evidence,
                        association_ids=set(),
                        pmids=set(),
                        outcomes=set(),
                        betas=[],
                    )
                buckets[key].add(row, beta)

    by_pollutant_window: dict[tuple[str, str], dict[str, AssociationBucket]] = defaultdict(dict)
    for (_, _, chapter), bucket in buckets.items():
        by_pollutant_window[(bucket.pollutant, bucket.window_type)][chapter] = bucket
    return dict(by_pollutant_window), all_chapters


# Famille B — profil généralisé, dérivé du persona et non de l'identité.
# Ces trois valeurs peuvent être légitimement fournies par un futur cas
# réel à l'inférence ; individual_id et persona_id ne le peuvent pas.
_PERSONA_PATHOLOGY = {
    "P1": "aucune",
    "P2": "aucune",
    "P3": "aucune",
    "P4": "cardiovasculaire",
    "P5": "respiratoire",
}
_PERSONA_AGE_CLASS = {
    "P1": "enfant",
    "P2": "adulte",
    "P3": "adulte",
    "P4": "senior",
    "P5": "adulte",
}


def derive_profile(
    persona_id: str,
    individual: "Individual | None",
    window_date_iso: str,
) -> tuple[str, str, str]:
    """Retourne (classe_age, grossesse, pathologie_preexistante).

    grossesse est déterminé dynamiquement : "oui" seulement si la fenêtre
    tombe dans la période [pregnancy_start, expected_delivery_date] de
    l'individu. Sans config individuelle (tests unitaires, usage isolé),
    grossesse retombe sur "non" par défaut plutôt que de lever une erreur.
    """
    classe_age = _PERSONA_AGE_CLASS.get(persona_id, "adulte")
    pathologie = _PERSONA_PATHOLOGY.get(persona_id, "aucune")

    grossesse = "non"
    if individual is not None and individual.pregnancy_start and individual.expected_delivery_date and window_date_iso:
        try:
            from datetime import date as _date
            current = _date.fromisoformat(window_date_iso[:10])
            if individual.pregnancy_start <= current <= individual.expected_delivery_date:
                grossesse = "oui"
        except ValueError:
            pass
    return classe_age, grossesse, pathologie


def load_trajectory(trajectory_path: Path) -> dict[str, dict[str, str]]:
    """Charge la couche de trajectoire (chapitre 3, étage 2), indexée par bag_id."""
    result: dict[str, dict[str, str]] = {}
    if not trajectory_path.exists():
        return result
    with open_text_input(trajectory_path) as handle:
        for row in csv.DictReader(handle):
            result[row["bag_id"]] = row
    return result


def load_windows(windows_path: Path) -> dict[str, dict[str, str]]:
    required = {
        "bag_id", "home_mean_exposure", "sum_exposure", "valid_slots", "home_minutes"
    }
    windows: dict[str, dict[str, str]] = {}
    with open_text_input(windows_path) as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, required, windows_path)
        for row in reader:
            windows[row["bag_id"]] = row
    return windows


def load_p0_by_chapter(p0_schedule_path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    required = {"individual_id", "calendar_year", "event_id", "event_name", "p0_value"}
    result: dict[tuple[str, str, str], dict[str, str]] = {}
    if not p0_schedule_path.exists():
        return result
    with p0_schedule_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, required, p0_schedule_path)
        for row in reader:
            chapter = EVENT_TO_CHAPTER.get(row["event_id"])
            if not chapter:
                continue
            key = (row["individual_id"], row["calendar_year"], chapter)
            p0 = float(row["p0_value"] or 0.0)
            current = result.get(key)
            if current is None or p0 > float(current["p0_value_max"]):
                result[key] = {
                    "p0_event_ids": row["event_id"],
                    "p0_value_max": f"{p0:.10f}",
                    "p0_event_names": row.get("event_name", ""),
                }
            elif current is not None and row["event_id"] not in current["p0_event_ids"].split(";"):
                current["p0_event_ids"] += f";{row['event_id']}"
    return result


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return default


def _exposure_signal(row: dict[str, str]) -> float:
    threshold = _safe_float(row.get("mean_threshold_value", ""), 1.0)
    if threshold <= 0:
        threshold = 1.0
    mean_ratio = _safe_float(row.get("mean_exposure", "")) / threshold
    max_ratio = _safe_float(row.get("max_exposure", "")) / threshold
    prop = _safe_float(row.get("proportion_above_threshold", ""))
    mean_component = min(1.0, mean_ratio / 2.0)
    max_component = min(1.0, max_ratio / 2.0)
    mil_component = 1.0 if row.get("mil_exceedance") == "1" else prop
    return max(0.0, min(1.0, 0.50 * mean_component + 0.30 * max_component + 0.20 * mil_component))


def _sample_negative_chapters(
    all_chapters: dict[str, str],
    positive_chapters: set[str],
    n: int,
    seed_text: str,
) -> list[tuple[str, str]]:
    candidates = sorted((ch, name) for ch, name in all_chapters.items() if ch not in positive_chapters)
    if n <= 0 or not candidates:
        return []
    rng = random.Random(seed_text)
    if n >= len(candidates):
        return candidates
    return sorted(rng.sample(candidates, n))


def _format(value: float) -> str:
    return f"{value:.8f}"


def generate_exposure_health_dataset(
    windows_path: Path,
    thresholds_path: Path,
    p0_schedule_path: Path,
    ctd_path: Path,
    output_path: Path,
    *,
    trajectory_path: Path | None = None,
    individuals: dict[str, "Individual"] | None = None,
    negative_ratio: float = 1.0,
    gzip_output: bool = True,
    core_chapters_only: bool = True,
) -> dict[str, int | float | str]:
    """Construit le dataset final exposition-santé (chapitre 4).

    trajectory_path : sortie de exposure_trajectory.generate_exposure_trajectory
        (chapitre 3, étage 2). Si absent, les colonnes de trajectoire sont
        laissées vides plutôt que de faire échouer la génération.
    individuals : config.individuals, utilisé pour dériver le profil
        généralisé (Famille B). Si absent, grossesse retombe sur "non".
    """
    if negative_ratio < 0:
        raise ValueError("negative_ratio doit être positif ou nul.")
    if not ctd_path.exists():
        raise FileNotFoundError(ctd_path)

    windows = load_windows(windows_path)
    trajectory = load_trajectory(trajectory_path) if trajectory_path else {}
    individuals = individuals or {}
    p0_by_chapter = load_p0_by_chapter(p0_schedule_path)
    allowed = CORE_ICD_CHAPTERS if core_chapters_only else None
    associations, all_chapters = build_association_summary(ctd_path, allowed_chapters=allowed)
    if not associations:
        raise ValueError("Aucune association CTD/ICD exploitable n'a été trouvée.")

    required_thresholds = {
        "bag_id", "individual_id", "persona_id", "household_id", "pollutant",
        "window_type", "window_start", "window_end", "year", "date",
        "mean_exposure", "max_exposure", "mean_exceedance", "max_exceedance",
        "mil_exceedance", "proportion_above_threshold", "excess_mean",
        "excess_max", "excess_burden",
    }

    output_rows = 0
    positive_rows = 0
    negative_rows = 0
    skipped_no_association = 0

    with open_text_input(thresholds_path) as thresholds_handle, open_text_output(output_path, gzip_output) as out_handle:
        reader = csv.DictReader(thresholds_handle)
        _require_columns(reader.fieldnames, required_thresholds, thresholds_path)
        writer = csv_writer(out_handle)
        writer.writerow(DATASET_COLUMNS)

        for row in reader:
            bag_id = row["bag_id"]
            window = windows.get(bag_id, {})
            pollutant = row["pollutant"]
            window_type = row["window_type"]
            positive = associations.get((pollutant, window_type), {})
            if not positive:
                skipped_no_association += 1
                continue

            exposure_signal = _exposure_signal(row)
            traj = trajectory.get(bag_id, {})
            classe_age, grossesse, pathologie = derive_profile(
                row["persona_id"], individuals.get(row["individual_id"]), row.get("date", "")
            )
            positive_chapters = set(positive)
            negative_count = int(math.ceil(len(positive_chapters) * negative_ratio))
            negatives = _sample_negative_chapters(
                all_chapters,
                positive_chapters,
                negative_count,
                seed_text=f"{bag_id}|{pollutant}|{window_type}",
            )

            candidates: list[tuple[str, str, int, AssociationBucket | None]] = []
            for chapter in sorted(positive_chapters):
                bucket = positive[chapter]
                candidates.append((chapter, bucket.icd_chapter_name, 1, bucket))
            for chapter, chapter_name in negatives:
                candidates.append((chapter, chapter_name, 0, None))

            for chapter, chapter_name, label, bucket in candidates:
                p0 = p0_by_chapter.get((row["individual_id"], row["year"], chapter))
                p0_value = _safe_float(p0["p0_value_max"], 0.0) if p0 else 0.0
                p0_relevance = 1.0 if p0 else 0.0
                persona_chapters = PERSONA_RELEVANT_CHAPTERS.get(row["persona_id"], set())
                persona_relevance = 1.0 if chapter in persona_chapters else 0.30

                if label == 1 and bucket is not None:
                    association_strength = bucket.association_strength
                    evidence_weight = bucket.evidence_weight
                    beta_mean = bucket.beta_mean
                    effect_measure_count = bucket.effect_measure_count
                    association_count = bucket.association_count
                    pmid_count = bucket.pmid_count
                    outcome_count = bucket.outcome_count
                    window_evidence = bucket.window_evidence
                    positive_rows += 1
                else:
                    association_strength = 0.0
                    evidence_weight = 0.0
                    beta_mean = 0.0
                    effect_measure_count = 0
                    association_count = 0
                    pmid_count = 0
                    outcome_count = 0
                    window_evidence = "unknown_sampled_negative"
                    negative_rows += 1

                writer.writerow([
                    bag_id,
                    row["individual_id"], row["persona_id"], row["household_id"],
                    pollutant, window_type, row["window_start"], row["window_end"],
                    row["year"], row["date"],
                    classe_age, grossesse, pathologie,
                    row["mean_exposure"],
                    window.get("home_mean_exposure", ""), row["max_exposure"],
                    window.get("sum_exposure", ""), window.get("valid_slots", ""),
                    window.get("home_minutes", ""), row["mean_exceedance"],
                    row["max_exceedance"], row["mil_exceedance"],
                    row["proportion_above_threshold"], row["excess_mean"],
                    row["excess_max"], row["excess_burden"],
                    traj.get("window_index", ""), traj.get("cumulative_exposure", ""),
                    traj.get("cumulative_excess_burden", ""),
                    traj.get("consecutive_exceedances", ""),
                    traj.get("max_consecutive_exceedances_to_date", ""),
                    traj.get("exposure_slope_7j", ""), traj.get("exposure_trend_direction", ""),
                    chapter, chapter_name,
                    str(label), _format(exposure_signal),
                    _format(association_strength), _format(beta_mean),
                    str(effect_measure_count), str(association_count), str(pmid_count),
                    str(outcome_count), _format(evidence_weight), window_evidence,
                    p0["p0_event_ids"] if p0 else "", _format(p0_value),
                    _format(p0_relevance), _format(persona_relevance),
                ])
                output_rows += 1

    return {
        "output_rows": output_rows,
        "positive_rows": positive_rows,
        "negative_rows": negative_rows,
        "skipped_windows_without_association": skipped_no_association,
        "candidate_icd_chapters": len(all_chapters),
        "negative_ratio": negative_ratio,
        "core_chapters_only": core_chapters_only,
        "output_path": str(output_path),
    }