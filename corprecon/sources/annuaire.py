"""
Wrapper pour l'API Recherche d'Entreprises (annuaire-entreprises.data.gouv.fr).

C'est une API GRATUITE du gouvernement français, sans inscription ni clé API.
Elle donne accès aux données du répertoire Sirene + INPI (RNE), et surtout
elle contient les DIRIGEANTS des sociétés — ce que l'API INSEE SIRENE seule
ne fournit pas.

Endpoint unique : GET https://recherche-entreprises.api.gouv.fr/search
Paramètres principaux :
  - q          : texte libre (nom, SIREN, SIRET, nom de dirigeant)
  - per_page   : nombre de résultats par page (max 25)
  - page       : numéro de page (pagination)

Rate limit : 7 requêtes/seconde (très généreux).

Ce module est la source PRINCIPALE pour :
  - Rechercher une entreprise par nom ou SIREN
  - Lister les dirigeants d'une entreprise
  - Rechercher toutes les entreprises liées à un nom de dirigeant
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from corprecon.models import Company, Mandate, Person

# --- Constants ---

# API publique du gouvernement — pas besoin de clé
BASE_URL = "https://recherche-entreprises.api.gouv.fr"

# Rate limit : 7 req/s → on espace de 0.5s pour eviter les 429
RATE_LIMIT_DELAY = 0.5

# Timeout pour les requêtes HTTP (en secondes)
REQUEST_TIMEOUT = 15.0

# Nombre max de résultats par page (l'API plafonne à 25)
MAX_PER_PAGE = 25

# Retry : nombre de tentatives et delai initial en cas de 429
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0


# ---------------------------------------------------------------------------
# HTTP helper avec retry automatique en cas de 429 (rate limit)
# ---------------------------------------------------------------------------


async def _get_with_retry(url: str, params: dict) -> dict:
    """
    Fait un GET avec retry automatique si l'API renvoie 429 (Too Many Requests).

    En cas de 429, on attend un delai croissant (2s, 4s, 8s) avant de retenter.
    Apres MAX_RETRIES echecs, on laisse l'exception remonter.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for attempt in range(MAX_RETRIES + 1):
            resp = await client.get(url, params=params)

            if resp.status_code == 429:
                if attempt < MAX_RETRIES:
                    # Attente exponentielle : 2s, 4s, 8s
                    wait = RETRY_BASE_DELAY * (2 ** attempt)
                    await asyncio.sleep(wait)
                    continue
                else:
                    # Plus de tentatives, on leve l'erreur
                    resp.raise_for_status()

            resp.raise_for_status()
            return resp.json()

    return {}  # ne devrait jamais arriver


# ---------------------------------------------------------------------------
# Parsing helpers — convertissent le JSON de l'API en modèles Pydantic
# ---------------------------------------------------------------------------


def _parse_company(result: dict) -> Company:
    """
    Transforme un résultat de l'API Annuaire en objet Company.

    L'API renvoie des champs comme :
      - siren            : "443061841"
      - nom_complet      : "GOOGLE FRANCE"
      - nature_juridique : "5710" (code INSEE de la forme juridique)
      - etat_administratif : "A" (actif) ou "C" (cessé)
      - date_creation    : "2002-05-16"
    """
    return Company(
        siren=result.get("siren", "000000000"),
        name=result.get("nom_complet", "Unknown"),
        legal_form=result.get("nature_juridique"),
        active=result.get("etat_administratif") == "A",
        creation_date=result.get("date_creation"),
    )


def _parse_dirigeant(dir_data: dict, company: Company) -> Optional[Person]:
    """
    Transforme un dirigeant de l'API en objet Person avec un Mandate.

    L'API distingue deux types de dirigeants :
    - "personne physique" : a un nom, prenom, date de naissance
    - "personne morale"   : a une denomination et un SIREN propre
      (ex: une holding qui est presidente d'une SAS)

    Les deux types sont retournes : les personnes physiques avec nom/prenom,
    les personnes morales avec la denomination comme last_name et le SIREN
    entre parentheses pour pouvoir remonter la chaine.
    """
    role = dir_data.get("qualite") or "Dirigeant"

    mandate = Mandate(
        role=role,
        company=company,
    )

    if dir_data.get("type_dirigeant") == "personne morale":
        # Personne morale = holding, commissaire aux comptes, etc.
        # On utilise la denomination comme last_name
        denomination = dir_data.get("denomination", "")
        if not denomination:
            return None
        siren_pm = dir_data.get("siren", "")
        # Ajouter le SIREN de la personne morale pour pouvoir remonter
        name = f"{denomination} (SIREN: {siren_pm})" if siren_pm else denomination
        return Person(
            first_name=None,
            last_name=name,
            mandates=[mandate],
        )
    else:
        # Personne physique = humain dirigeant
        nom = dir_data.get("nom", "")
        prenoms = dir_data.get("prenoms", "")
        if not nom:
            return None
        return Person(
            first_name=prenoms.title() if prenoms else None,
            last_name=nom.upper(),
            mandates=[mandate],
        )


# ---------------------------------------------------------------------------
# Fonctions publiques async
# ---------------------------------------------------------------------------


async def search_companies(
    query: str,
    *,
    max_results: int = 10,
) -> list[tuple[Company, list[Person]]]:
    """
    Recherche des entreprises par texte libre.

    Peut chercher par :
    - Nom d'entreprise : "Google France"
    - SIREN            : "443061841"
    - Nom de dirigeant : "Jean Dupont" (l'API cherche aussi dans les dirigeants)

    Args:
        query       : texte de recherche
        max_results : nombre max d'entreprises à retourner (max 25)

    Returns:
        Liste de tuples (Company, [dirigeants Person]) pour chaque entreprise trouvée.
    """
    # Limiter à 25 (max de l'API)
    per_page = min(max_results, MAX_PER_PAGE)

    # Appel avec retry automatique en cas de 429
    data = await _get_with_retry(
        f"{BASE_URL}/search",
        params={"q": query, "per_page": per_page},
    )

    results: list[tuple[Company, list[Person]]] = []

    for item in data.get("results", []):
        company = _parse_company(item)

        # Parser tous les dirigeants personnes physiques
        directors: list[Person] = []
        for dir_data in item.get("dirigeants", []):
            person = _parse_dirigeant(dir_data, company)
            if person is not None:
                directors.append(person)

        results.append((company, directors))

    return results


async def get_company(siren: str) -> tuple[Company, list[Person]]:
    """
    Récupère une entreprise par son SIREN et liste ses dirigeants.

    C'est un raccourci pour search_companies avec un SIREN exact.

    Args:
        siren : numéro SIREN à 9 chiffres

    Returns:
        Tuple (Company, liste des dirigeants Person)

    Raises:
        ValueError si aucune entreprise trouvée pour ce SIREN
    """
    results = await search_companies(siren, max_results=1)

    if not results:
        raise ValueError(f"Aucune entreprise trouvee pour le SIREN {siren}")

    return results[0]


async def search_person_mandates(name: str, *, max_results: int = 25) -> list[Person]:
    """
    Recherche tous les mandats d'une personne par son nom.

    Stratégie :
    1. On cherche le nom dans l'API (qui cherche aussi dans les dirigeants)
    2. Pour chaque entreprise trouvée, on vérifie si le nom apparaît
       dans la liste des dirigeants
    3. On regroupe tous les mandats sous le même objet Person

    Args:
        name        : nom complet (ex: "Jean Dupont")
        max_results : nombre max d'entreprises à scanner

    Returns:
        Liste de Person avec tous leurs mandats regroupés.
        En pratique, souvent une seule Person avec N mandats.
    """
    results = await search_companies(name, max_results=max_results)

    # On va regrouper les mandats par personne
    # Clé = (prénom en minuscule, nom en minuscule)
    persons_map: dict[tuple[str, str], Person] = {}

    # Préparer le nom recherché pour le matching
    # On découpe en parties pour comparer nom de famille
    search_parts = name.upper().split()

    for company, directors in results:
        for director in directors:
            # Vérifier si ce dirigeant correspond au nom recherché
            # On compare le nom de famille (dernière partie du nom recherché)
            director_name = director.last_name.upper()
            match = any(part in director_name for part in search_parts)

            if not match:
                continue

            # Clé unique pour regrouper les mandats d'une même personne
            key = (
                (director.first_name or "").lower(),
                director.last_name.lower(),
            )

            if key not in persons_map:
                # Première occurrence : créer la personne
                persons_map[key] = Person(
                    first_name=director.first_name,
                    last_name=director.last_name,
                    birth_date=director.birth_date,
                    mandates=[],
                )

            # Ajouter le mandat à cette personne
            persons_map[key].mandates.extend(director.mandates)

    return list(persons_map.values())
