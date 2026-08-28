"""
Aide partagee pour paralleliser le traitement des PMIDs dans les runners
d'agents LLM (pollutant/outcome/effect_measure).

Ceci ne change RIEN a ce que chaque PMID produit : `worker(pmid)` reste
exactement la meme fonction qu'avant (meme prompt, meme parsing, meme sortie
ecrite sur disque). Seul l'ORDONNANCEMENT change : plusieurs PMIDs sont
traites en meme temps au lieu d'un par un.

`--workers 1` (ou l'absence de ce flag) redonne exactement le comportement
sequentiel d'origine.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

T = TypeVar("T")


def run_pmids(
    pmids: list[str],
    worker: Callable[[str], T],
    max_workers: int = 1,
) -> list[T]:
    """Appelle worker(pmid) pour chaque pmid, en serie ou en parallele.

    Retourne les resultats dans l'ordre de COMPLETION (pas l'ordre d'entree)
    quand max_workers > 1 ; dans l'ordre d'entree quand max_workers <= 1.
    """
    if max_workers <= 1:
        return [worker(pmid) for pmid in pmids]

    results: list[T] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, pmid): pmid for pmid in pmids}

        for future in as_completed(futures):
            results.append(future.result())

    return results
