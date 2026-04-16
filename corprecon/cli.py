"""
CorpRecon CLI — powered by Typer.

Usage simple, comme Sherlock :
  corprecon "Jean Dupont"          -> cherche les mandats de cette personne
  corprecon 443061841              -> affiche l'entreprise et ses dirigeants
  corprecon 443061841 --cross      -> croisement des mandats des dirigeants
  corprecon 443061841 -x           -> idem (raccourci)
"""

from __future__ import annotations

import asyncio
import re

import typer

from corprecon import __version__
from corprecon.crosser import cross_mandates, format_cross_result
from corprecon.sources import annuaire

app = typer.Typer(
    name="corprecon",
    help="OSINT tool to map French corporate mandate networks.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"corprecon {__version__}")
        raise typer.Exit()


def _is_siren(query: str) -> bool:
    """Un SIREN c'est exactement 9 chiffres."""
    return bool(re.match(r"^\d{9}$", query.strip()))


@app.command()
def main(
    query: str = typer.Argument(
        ...,
        help='Name ("Jean Dupont") or SIREN (443061841)',
    ),
    cross: bool = typer.Option(
        False,
        "--cross",
        "-x",
        help="Cross-reference mandates across directors (SIREN only)",
    ),
    max_results: int = typer.Option(
        25,
        "--max",
        "-m",
        help="Max results to scan",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """
    OSINT tool to map French corporate mandate networks.

    Auto-detects input type: 9 digits = SIREN, anything else = person name.
    """
    query = query.strip()

    if _is_siren(query):
        if cross:
            _do_cross(query)
        else:
            _do_company(query)
    else:
        if cross:
            typer.echo("Error: --cross requires a SIREN, not a name.")
            raise typer.Exit(code=1)
        _do_person(query, max_results)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _do_person(name: str, max_results: int) -> None:
    """Recherche des mandats d'une personne par son nom."""
    typer.echo(f"[*] Searching mandates for: {name}")

    persons = asyncio.run(
        annuaire.search_person_mandates(name, max_results=max_results)
    )

    if not persons:
        typer.echo("[-] No results found.")
        raise typer.Exit()

    for p in persons:
        active = len(p.active_mandates)
        total = len(p.mandates)
        typer.echo(f"\n[+] {p.full_name} -- {active} active / {total} total")

        for m in p.mandates:
            status = "active" if m.is_active else "ended"
            typer.echo(
                f"    [{status}] {m.role} @ {m.company.name} ({m.company.siren})"
            )


def _do_company(siren: str) -> None:
    """Affiche une entreprise et ses dirigeants."""
    typer.echo(f"[*] Looking up SIREN: {siren}")

    comp, directors = asyncio.run(annuaire.get_company(siren))

    status = "ACTIVE" if comp.active else "INACTIVE"
    typer.echo(f"\n[+] {comp.name} ({comp.siren}) [{status}]")
    if comp.legal_form:
        typer.echo(f"    Legal form: {comp.legal_form}")
    if comp.creation_date:
        typer.echo(f"    Created: {comp.creation_date}")

    typer.echo(f"\n[+] Directors ({len(directors)}):")
    if not directors:
        typer.echo("    (no directors found)")
    for d in directors:
        for m in d.mandates:
            typer.echo(f"    - {d.full_name} -- {m.role}")


def _do_cross(siren: str) -> None:
    """Croisement des mandats des dirigeants d'une entreprise."""
    typer.echo(f"[*] Cross-referencing mandates for SIREN: {siren}")

    result = asyncio.run(cross_mandates(siren))
    typer.echo(f"\n{format_cross_result(result)}")


if __name__ == "__main__":
    app()
