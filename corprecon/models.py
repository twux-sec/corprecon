"""
Pydantic data models for CorpRecon.

Three core models:
- Company  : represents a legal entity (société) identified by its SIREN number
- Person   : represents a director/officer (dirigeant) of one or more companies
- Mandate  : represents the link between a Person and a Company (mandat social)

These models are used everywhere: API responses are parsed into them,
the crosser logic operates on them, and the CLI formats them for display.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class Company(BaseModel):
    """A French legal entity (unité légale) from the SIRENE register."""

    siren: str = Field(
        ...,
        min_length=9,
        max_length=9,
        pattern=r"^\d{9}$",
        description="9-digit SIREN identifier (unique per legal entity)",
    )
    name: str = Field(
        ...,
        description="Company trade name or legal denomination",
    )
    # Legal form code from INSEE nomenclature (e.g. "5710" = SAS)
    legal_form: Optional[str] = Field(
        default=None,
        description="INSEE legal form code (categorieJuridiqueUniteLegale)",
    )
    # Is the company currently active in the SIRENE register?
    active: bool = Field(
        default=True,
        description="True if the company is currently registered as active",
    )
    creation_date: Optional[date] = Field(
        default=None,
        description="Date the company was created (dateCreationUniteLegale)",
    )


class Mandate(BaseModel):
    """
    A social mandate — the formal link between a person and a company.

    Examples of roles: Gérant, Président, Directeur général,
    Administrateur, Commissaire aux comptes, etc.
    """

    role: str = Field(
        ...,
        description="Official role title (e.g. 'Président', 'Gérant')",
    )
    company: Company = Field(
        ...,
        description="The company where this mandate is held",
    )
    # Start date of the mandate (if known from the source)
    start_date: Optional[date] = Field(
        default=None,
        description="Date the mandate started",
    )
    # End date — None means the mandate is presumably still active
    end_date: Optional[date] = Field(
        default=None,
        description="Date the mandate ended (None = still active)",
    )

    @property
    def is_active(self) -> bool:
        """A mandate is considered active if it has no end date."""
        return self.end_date is None


class Person(BaseModel):
    """
    A company director/officer (dirigeant).

    A person can hold multiple mandates across different companies,
    which is exactly what CorpRecon aims to map.
    """

    first_name: Optional[str] = Field(
        default=None,
        description="First name (prénom) — may be None for legal entities acting as directors",
    )
    last_name: str = Field(
        ...,
        description="Last name (nom) or legal entity name if the director is a company",
    )
    # Birth date helps disambiguate people with the same name
    birth_date: Optional[date] = Field(
        default=None,
        description="Date of birth (used for disambiguation)",
    )
    # All known mandates for this person
    mandates: list[Mandate] = Field(
        default_factory=list,
        description="List of mandates held by this person",
    )

    @property
    def full_name(self) -> str:
        """Return 'First Last' or just 'Last' if no first name."""
        if self.first_name:
            return f"{self.first_name} {self.last_name}"
        return self.last_name

    @property
    def active_mandates(self) -> list[Mandate]:
        """Filter to only currently active mandates."""
        return [m for m in self.mandates if m.is_active]
