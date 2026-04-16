"""
Logique de croisement des mandats.

C'est le coeur de CorpRecon : a partir d'une entreprise cible, on recupere
tous ses dirigeants, puis pour chaque dirigeant on cherche ses AUTRES mandats
pour detecter des structures communes (entreprises ou plusieurs dirigeants
de la cible apparaissent ensemble).

Exemple concret :
  On investigue la societe A (SIREN: 123456789).
  La societe A a 3 dirigeants : Alice, Bob, Charlie.
  Alice est aussi gerante de la societe B.
  Bob est aussi administrateur de la societe B et president de la societe C.
  -> La societe B est une "structure commune" (Alice + Bob presents).
  -> Ce pattern revele souvent des holdings ou des entites liees.

Sources de donnees :
  - API Recherche d'Entreprises pour les dirigeants et la recherche par nom
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field

from corprecon.models import Company, Mandate, Person
from corprecon.sources import annuaire


@dataclass
class CrossResult:
    """
    Resultat d'une analyse de croisement sur une entreprise.

    Attributes:
        target    : l'entreprise investiguee
        directors : tous les dirigeants trouves pour cette entreprise
        shared    : dict qui mappe chaque entreprise (par SIREN) a la liste
                    des dirigeants de la cible qui y apparaissent aussi
    """

    target: Company
    directors: list[Person] = field(default_factory=list)
    # Cle = SIREN de l'entreprise partagee
    # Valeur = liste de tuples (Person, Mandate) montrant qui a quel role
    shared: dict[str, list[tuple[Person, Mandate]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @property
    def shared_companies(self) -> dict[str, list[tuple[Person, Mandate]]]:
        """
        Ne retourne que les entreprises ou 2+ dirigeants de la cible
        apparaissent — et exclut la cible elle-meme.
        C'est la ou c'est interessant pour l'investigation.
        """
        return {
            siren: persons
            for siren, persons in self.shared.items()
            # Exclure la cible elle-meme et exiger au moins 2 liens
            if siren != self.target.siren and len(persons) >= 2
        }


async def cross_mandates(siren: str) -> CrossResult:
    """
    Pipeline complet de croisement pour une entreprise.

    Etapes :
    1. Recuperer l'entreprise cible et ses dirigeants via l'API Annuaire
    2. Pour chaque dirigeant, chercher son nom pour trouver tous ses mandats
    3. Construire la carte des entreprises ou plusieurs dirigeants se croisent

    Args:
        siren : SIREN a 9 chiffres de l'entreprise a investiguer

    Returns:
        CrossResult avec les dirigeants et les structures partagees detectees
    """
    # Etape 1 : recuperer la cible et ses dirigeants
    company, directors = await annuaire.get_company(siren)
    result = CrossResult(target=company, directors=directors)

    # Etape 2 : pour chaque dirigeant, chercher ses autres mandats
    # On fait les recherches sequentiellement pour respecter le rate limit
    for director in directors:
        # Chercher par le nom complet du dirigeant
        persons = await annuaire.search_person_mandates(director.full_name)

        # Trouver la personne correspondante dans les resultats
        for person in persons:
            if person.last_name.upper() == director.last_name.upper():
                # Fusionner les mandats decouverts dans l'objet directeur
                director.mandates.extend(person.mandates)

                # Etape 3 : enregistrer chaque mandat pour le croisement
                for mandate in person.mandates:
                    result.shared[mandate.company.siren].append(
                        (director, mandate)
                    )
                break

        # Respecter le rate limit entre les recherches
        await asyncio.sleep(annuaire.RATE_LIMIT_DELAY)

    return result


def format_cross_result(result: CrossResult) -> str:
    """
    Formate un CrossResult en texte lisible pour la CLI.

    Affiche :
    - Infos de l'entreprise cible
    - Liste des dirigeants avec leur nombre de mandats
    - Structures partagees (la partie interessante)
    """
    lines: list[str] = []

    # En-tete
    status = "ACTIVE" if result.target.active else "INACTIVE"
    lines.append(f"=== {result.target.name} ({result.target.siren}) [{status}] ===")
    lines.append("")

    # Section dirigeants
    lines.append(f"Directors ({len(result.directors)}):")
    for d in result.directors:
        active = len(d.active_mandates)
        total = len(d.mandates)
        lines.append(f"  - {d.full_name} -- {active} active / {total} total mandates")

    # Section structures partagees (l'or de l'investigation)
    shared = result.shared_companies
    if shared:
        lines.append("")
        lines.append(f"Shared structures ({len(shared)}):")
        for siren, persons in shared.items():
            # Recuperer le nom de l'entreprise depuis le premier mandat
            company_name = persons[0][1].company.name
            names = ", ".join(p.full_name for p, _ in persons)
            lines.append(f"  * {company_name} ({siren}) -- linked directors: {names}")
    else:
        lines.append("")
        lines.append("No shared structures detected.")

    return "\n".join(lines)
