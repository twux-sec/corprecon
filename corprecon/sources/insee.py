"""
INSEE SIRENE v3.11 API wrapper.

The SIRENE API gives access to the French national register of companies.
Docs: https://portail-api.insee.fr (Catalogue → API Sirene)

Authentication: API Key passed in the header 'X-INSEE-Api-Key-Integration'.
  1. Create a "Simple" app on portail-api.insee.fr
  2. Subscribe to API Sirene (plan "Public")
  3. Copy the API key from the Souscriptions tab

Rate limit: 30 requests/minute on public plan.

This module exposes two main functions:
- search_by_name()  : find legal entities matching a person's name
- search_by_siren() : get details of a specific company + its directors
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

from corprecon.models import Company, Mandate, Person

# Load .env file so INSEE_API_KEY is available via os.environ
load_dotenv()

# --- Constants ---

# Base URL for the SIRENE v3.11 API (confirmed from official docs)
BASE_URL = "https://api.insee.fr/api-sirene/3.11"

# INSEE public plan: 30 req/min → we space calls by 2 seconds to be safe
RATE_LIMIT_DELAY = 2.0

# Default timeout for HTTP requests (seconds)
REQUEST_TIMEOUT = 15.0


def _get_api_key() -> str:
    """
    Read the INSEE API key from environment.
    Raises a clear error if the key is not set.
    """
    key = os.environ.get("INSEE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "INSEE_API_KEY is not set. "
            "Create a 'Simple' app on portail-api.insee.fr, subscribe to "
            "API Sirene, and copy the API key to your .env file."
        )
    return key


def _build_headers() -> dict[str, str]:
    """
    Build HTTP headers for the INSEE API.
    Auth is via the 'X-INSEE-Api-Key-Integration' header (not Bearer).
    """
    return {
        "X-INSEE-Api-Key-Integration": _get_api_key(),
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Parsing helpers — transform raw INSEE JSON into our Pydantic models
# ---------------------------------------------------------------------------


def _parse_company(unit: dict) -> Company:
    """
    Parse a single 'uniteLegale' object from the INSEE response
    into our Company model.

    The INSEE API nests the current state inside 'periodesUniteLegale'.
    The first period (index 0) is always the most recent one.
    """
    # The most recent period holds the current denomination and status
    periods = unit.get("periodesUniteLegale", [{}])
    current = periods[0] if periods else {}

    # For companies: denominationUniteLegale
    # For sole proprietors: built from first + last name
    name = current.get("denominationUniteLegale") or ""
    if not name:
        # Fallback for individual enterprises (entreprise individuelle)
        first = unit.get("prenom1UniteLegale", "")
        last = unit.get("nomUniteLegale", "")
        name = f"{first} {last}".strip() or "Unknown"

    # etatAdministratifUniteLegale: "A" = active, "C" = ceased
    active = current.get("etatAdministratifUniteLegale") == "A"

    return Company(
        siren=unit.get("siren", "000000000"),
        name=name,
        legal_form=current.get("categorieJuridiqueUniteLegale"),
        active=active,
        creation_date=unit.get("dateCreationUniteLegale"),
    )


def _parse_person_from_dirigeant(dir_data: dict, company: Company) -> Person:
    """
    Parse a 'dirigeant' entry from an INSEE response into a Person
    with a single Mandate attached.

    INSEE distinguishes between:
    - Physical persons (dirigeants physiques): have first/last name
    - Legal entities (dirigeants moraux): have a denomination/SIREN
    """
    first_name = dir_data.get("prenomUsuelDirigeant")
    last_name = dir_data.get("nomDirigeant") or dir_data.get(
        "denominationDirigeant", "Unknown"
    )
    role = dir_data.get("qualiteDirigeant", "Dirigeant")

    mandate = Mandate(
        role=role,
        company=company,
        start_date=dir_data.get("dateDebutMandat"),
        end_date=dir_data.get("dateFinMandat"),
    )

    return Person(
        first_name=first_name,
        last_name=last_name,
        birth_date=dir_data.get("dateNaissanceDirigeant"),
        mandates=[mandate],
    )


# ---------------------------------------------------------------------------
# Public async API functions
# ---------------------------------------------------------------------------


async def search_by_name(
    name: str,
    *,
    max_results: int = 20,
) -> list[Person]:
    """
    Search for a person across all company directors in the SIRENE register.

    Strategy: query the 'nomUniteLegale' field to find legal entities
    where this person's name appears, then collect director info.

    Args:
        name: full name to search for (e.g. "Jean Dupont")
        max_results: max number of legal entities to scan

    Returns:
        List of Person objects with their mandates populated.
    """
    headers = _build_headers()

    # INSEE uses a custom query language (similar to LDAP filters)
    # We search for the name in the director surname field
    parts = name.strip().split()
    if len(parts) >= 2:
        # Assume "FirstName LastName" → search last name in nomUniteLegale
        query = f'periode(nomUniteLegale:"{parts[-1]}")'
    else:
        query = f'periode(nomUniteLegale:"{name}")'

    # v3.11 uses /siren for legal entity search (not /siret)
    url = f"{BASE_URL}/siren"
    params = {
        "q": query,
        "nombre": max_results,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    # Collect unique persons from the results
    # Key = (first_name, last_name) to group mandates under the same person
    persons_map: dict[tuple, Person] = {}

    # v3.11 returns 'unitesLegales' (not 'etablissements')
    for unit in data.get("unitesLegales", []):
        company = _parse_company(unit)

        # In v3.11, nomUniteLegale is inside periodesUniteLegale (not at root)
        periods = unit.get("periodesUniteLegale", [{}])
        current = periods[0] if periods else {}
        nom = current.get("nomUniteLegale", "") or ""
        prenom = unit.get("prenom1UniteLegale", "") or ""

        # For individual enterprises: nom = last name, prenom = first name
        # For corporations: nom is empty, name is in denominationUniteLegale
        if not nom:
            continue

        key = (prenom.lower(), nom.lower())

        if key not in persons_map:
            persons_map[key] = Person(
                first_name=prenom or None,
                last_name=nom,
                mandates=[],
            )

        # Add a mandate linking this person to the company
        persons_map[key].mandates.append(
            Mandate(
                role="Dirigeant",
                company=company,
            )
        )

    return list(persons_map.values())


async def search_by_siren(siren: str) -> tuple[Company, list[Person]]:
    """
    Fetch a company by SIREN and list all its known directors.

    Args:
        siren: 9-digit SIREN number

    Returns:
        Tuple of (Company, list of Person with one Mandate each)
    """
    headers = _build_headers()

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # Get the legal entity details via /siren/{siren}
        resp = await client.get(
            f"{BASE_URL}/siren/{siren}",
            headers=headers,
        )
        resp.raise_for_status()
        unit_data = resp.json().get("uniteLegale", {})
        company = _parse_company(unit_data)

    # Extract director info from the legal entity itself
    # Note: SIRENE only has director info for individual enterprises
    # (entreprises individuelles), not for corporations (SAS, SARL, etc.)
    # For full director data, Pappers API is needed (V1.5)
    directors: list[Person] = []
    nom = unit_data.get("nomUniteLegale", "")
    prenom = unit_data.get("prenom1UniteLegale", "")
    if nom:
        directors.append(
            Person(
                first_name=prenom or None,
                last_name=nom,
                mandates=[
                    Mandate(role="Dirigeant", company=company)
                ],
            )
        )

    return company, directors
