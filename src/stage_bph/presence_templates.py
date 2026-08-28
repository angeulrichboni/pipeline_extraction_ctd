"""Presence scenarios for step A.

The two schedules are transcribed from Annexe B.1 and B.2. Empty/grey cells in
the source tables are encoded as ``absent``. Time ranges are expanded to 96
15-minute slots per day.
"""
from __future__ import annotations

PIECES = {"sejour", "chambre", "cuisine", "sdb", "absent"}
TYPES_PRESENCE = ("Personne1", "Personne2", "Personnes3_4")


def _slot(time_label: str) -> int:
    if time_label == "24h":
        return 96
    hour_text, _, minute_text = time_label.partition("h")
    hour = int(hour_text)
    minute = int(minute_text or "0")
    if minute not in (0, 15, 30, 45):
        raise ValueError(f"Minute invalide pour un pas de 15 min: {time_label}")
    return hour * 4 + minute // 15


def _build_schedule(rows: list[tuple[str, str, dict[str, str]]]) -> dict[str, list[str]]:
    schedules = {tp: ["absent"] * 96 for tp in TYPES_PRESENCE}
    filled = [False] * 96
    for start, end, values in rows:
        start_slot = _slot(start)
        end_slot = _slot(end)
        if not 0 <= start_slot < end_slot <= 96:
            raise ValueError(f"Plage horaire invalide: {start}-{end}")
        for creneau in range(start_slot, end_slot):
            if filled[creneau]:
                raise ValueError(f"Creneau renseigne deux fois: {creneau}")
            for tp in TYPES_PRESENCE:
                piece = values.get(tp, "absent")
                if piece not in PIECES:
                    raise ValueError(f"Piece invalide: {piece}")
                schedules[tp][creneau] = piece
            filled[creneau] = True
    missing = [i for i, ok in enumerate(filled) if not ok]
    if missing:
        raise ValueError(f"Creneaux non renseignes: {missing}")
    return schedules


# ── Annexe B.1 — Scénario SEMAINE ─────────────────────────────────────────────
PRESENCE_SEMAINE = _build_schedule([
    ("0h",    "6h",    {"Personne1": "chambre",  "Personne2": "chambre",  "Personnes3_4": "chambre"}),
    ("6h",    "6h30",  {"Personne1": "cuisine",  "Personne2": "sdb",      "Personnes3_4": "chambre"}),
    ("6h30",  "7h",    {"Personne1": "sdb",      "Personne2": "cuisine",  "Personnes3_4": "chambre"}),
    ("7h",    "7h15",  {                                                    "Personnes3_4": "cuisine"}),
    ("7h15",  "7h30",  {                                                    "Personnes3_4": "sdb"}),
    ("7h30",  "7h45",  {                                                    "Personnes3_4": "cuisine"}),
    ("7h45",  "8h",    {                                                    "Personnes3_4": "sdb"}),
    # Personne1 et Personne2 absents 8h–12h (départ matin)
    ("8h",    "8h30",  {}),
    ("8h30",  "9h",    {}),
    ("9h",    "12h",   {}),
    # Retour déjeuner Personne1 uniquement (12h–13h)
    ("12h",   "12h15", {"Personne1": "sejour"}),
    ("12h15", "12h30", {"Personne1": "cuisine"}),
    ("12h30", "12h45", {"Personne1": "sejour"}),
    ("12h45", "13h",   {"Personne1": "cuisine"}),
    # Personne1 et Personne2 absents 13h–17h (retour bureau)
    ("13h",   "17h",   {}),
    # Retour Personnes3_4 à 17h
    ("17h",   "18h",   {                                                    "Personnes3_4": "chambre"}),
    # Retour Personne1 et Personne2 à 18h
    ("18h",   "18h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("18h15", "18h30", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("18h30", "18h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("18h45", "19h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("19h",   "19h15", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("19h15", "19h30", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("19h30", "19h45", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("19h45", "20h",   {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("20h",   "21h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("21h",   "21h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("21h15", "21h30", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("21h30", "21h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("21h45", "22h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("22h",   "23h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("23h",   "24h",   {"Personne1": "chambre",  "Personne2": "chambre",  "Personnes3_4": "chambre"}),
])


# ── Annexe B.2 — Scénario WEEK-END ────────────────────────────────────────────
PRESENCE_WEEKEND = _build_schedule([
    ("0h",    "8h",    {"Personne1": "chambre",  "Personne2": "chambre",  "Personnes3_4": "chambre"}),
    ("8h",    "8h30",  {"Personne1": "cuisine",  "Personne2": "sdb",      "Personnes3_4": "chambre"}),
    ("8h30",  "9h",    {"Personne1": "sdb",      "Personne2": "cuisine",  "Personnes3_4": "chambre"}),
    ("9h",    "9h15",  {                          "Personne2": "sejour",   "Personnes3_4": "cuisine"}),
    ("9h15",  "9h30",  {                          "Personne2": "sejour",   "Personnes3_4": "sdb"}),
    ("9h30",  "9h45",  {                          "Personne2": "sejour",   "Personnes3_4": "cuisine"}),
    ("9h45",  "10h",   {                          "Personne2": "sejour",   "Personnes3_4": "sdb"}),
    ("10h",   "10h15", {                          "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("10h15", "10h30", {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("10h30", "10h45", {                          "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("10h45", "11h",   {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("11h",   "11h15", {                          "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("11h15", "11h30", {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("11h30", "11h45", {                          "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("11h45", "12h",   {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("12h",   "12h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("12h15", "12h30", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("12h30", "12h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("12h45", "13h",   {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("13h",   "14h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("14h",   "14h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("14h15", "14h30", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("14h30", "14h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("14h45", "15h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    # Tous absents 15h-17h (promenade / sortie) selon fiche B.2
    ("15h",   "17h",   {}),
    ("17h",   "18h",   {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("18h",   "18h15", {                          "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("18h15", "18h30", {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("18h30", "18h45", {                          "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("18h45", "19h",   {                          "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("19h",   "19h15", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("19h15", "19h30", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("19h30", "19h45", {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("19h45", "20h",   {"Personne1": "cuisine",  "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("20h",   "21h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("21h",   "21h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("21h15", "21h30", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("21h30", "21h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("21h45", "22h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("22h",   "22h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("22h15", "22h30", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("22h30", "22h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("22h45", "23h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("23h",   "23h15", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("23h15", "23h30", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
    ("23h30", "23h45", {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "sejour"}),
    ("23h45", "24h",   {"Personne1": "sejour",   "Personne2": "sejour",   "Personnes3_4": "chambre"}),
])


def get_piece(type_presence: str, type_jour: str, creneau: int) -> str:
    """Return the room occupied at a given 15-minute slot."""
    if type_presence not in TYPES_PRESENCE:
        raise KeyError(f"type_presence inconnu: {type_presence}")
    if not 0 <= creneau < 96:
        raise ValueError(f"creneau doit etre entre 0 et 95: {creneau}")
    if type_jour == "semaine":
        return PRESENCE_SEMAINE[type_presence][creneau]
    if type_jour == "weekend":
        return PRESENCE_WEEKEND[type_presence][creneau]
    raise ValueError(f"type_jour inconnu: {type_jour}")