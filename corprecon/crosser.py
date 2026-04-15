"""
Mandate cross-detection logic.

This is the core intelligence of CorpRecon: given a company, it finds
all directors, then checks each director's OTHER mandates to detect
shared structures (companies where multiple directors of the original
company also hold positions).

Example use case:
  You investigate company A (SIREN: 123456789).
  Company A has 3 directors: Alice, Bob, Charlie.
  Alice is also director of company B.
  Bob is also director of company B and company C.
  → Company B is a "shared structure" (Alice + Bob both present).
  → This pattern often signals holding structures or related entities.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field

from corprecon.models import Company, Mandate, Person
from corprecon.sources import insee


@dataclass
class CrossResult:
    """
    Result of a cross-detection analysis on a single company.

    Attributes:
        target: the company being investigated
        directors: all directors found for the target company
        shared: dict mapping each shared company (by SIREN) to the list
                of directors from the target company who also appear there
    """

    target: Company
    directors: list[Person] = field(default_factory=list)
    # Key = SIREN of the shared company
    # Value = list of (Person, Mandate) tuples showing who holds what role
    shared: dict[str, list[tuple[Person, Mandate]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @property
    def shared_companies(self) -> dict[str, list[tuple[Person, Mandate]]]:
        """Return only companies where 2+ directors from the target appear."""
        return {
            siren: persons
            for siren, persons in self.shared.items()
            # Exclude the target company itself and require at least 2 links
            if siren != self.target.siren and len(persons) >= 2
        }


async def cross_mandates(siren: str) -> CrossResult:
    """
    Full cross-detection pipeline for a company.

    Steps:
    1. Fetch the target company and its directors via INSEE
    2. For each director, search their name to find all their mandates
    3. Build a map of all companies where multiple directors overlap

    Args:
        siren: 9-digit SIREN of the company to investigate

    Returns:
        CrossResult with directors and detected shared structures
    """
    # Step 1: get the target company and its known directors
    company, directors = await insee.search_by_siren(siren)
    result = CrossResult(target=company, directors=directors)

    # Step 2: for each director, find all their other mandates
    # We run these sequentially to respect INSEE rate limits
    for director in directors:
        # Search by the director's full name
        persons = await insee.search_by_name(director.full_name)

        # Find the matching person in results (same last name)
        for person in persons:
            if person.last_name.lower() == director.last_name.lower():
                # Merge mandates we discovered into the director object
                director.mandates.extend(person.mandates)

                # Step 3: record each mandate for cross-detection
                for mandate in person.mandates:
                    result.shared[mandate.company.siren].append(
                        (director, mandate)
                    )
                break

        # Rate limiting: wait between searches
        await asyncio.sleep(insee.RATE_LIMIT_DELAY)

    return result


def format_cross_result(result: CrossResult) -> str:
    """
    Format a CrossResult as a human-readable string for CLI output.

    Shows:
    - Target company info
    - List of directors and their total mandates
    - Shared structures (the interesting part)
    """
    lines: list[str] = []

    # Header
    status = "ACTIVE" if result.target.active else "INACTIVE"
    lines.append(f"=== {result.target.name} ({result.target.siren}) [{status}] ===")
    lines.append("")

    # Directors section
    lines.append(f"Directors ({len(result.directors)}):")
    for d in result.directors:
        active = len(d.active_mandates)
        total = len(d.mandates)
        lines.append(f"  - {d.full_name} — {active} active / {total} total mandates")

    # Shared structures section (the gold)
    shared = result.shared_companies
    if shared:
        lines.append("")
        lines.append(f"Shared structures ({len(shared)}):")
        for siren, persons in shared.items():
            # Get company name from the first mandate
            company_name = persons[0][1].company.name
            names = ", ".join(p.full_name for p, _ in persons)
            lines.append(f"  * {company_name} ({siren}) — linked directors: {names}")
    else:
        lines.append("")
        lines.append("No shared structures detected.")

    return "\n".join(lines)
