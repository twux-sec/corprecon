"""
CorpRecon CLI — powered by Typer.

Three commands:
  corprecon person "Nom Prénom"  → list all mandates for a person
  corprecon company SIREN        → list all directors of a company
  corprecon cross SIREN          → detect shared structures across directors

Typer handles argument parsing, help generation, and error display.
We use asyncio.run() to bridge sync CLI calls to our async API functions.
"""

from __future__ import annotations

import asyncio

import typer

from corprecon import __version__
from corprecon.crosser import cross_mandates, format_cross_result
from corprecon.sources import insee

# Main Typer app — the entry point defined in pyproject.toml
app = typer.Typer(
    name="corprecon",
    help="OSINT tool to map French corporate mandate networks.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """Print version and exit when --version is passed."""
    if value:
        typer.echo(f"corprecon {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,  # Process this option before anything else
    ),
) -> None:
    """CorpRecon — map French corporate mandate networks from public data."""


# ---------------------------------------------------------------------------
# Command: person
# ---------------------------------------------------------------------------


@app.command()
def person(
    name: str = typer.Argument(
        ...,
        help='Full name to search for (e.g. "Victor Pacoud")',
    ),
    max_results: int = typer.Option(
        20,
        "--max",
        "-m",
        help="Maximum number of results to return",
    ),
) -> None:
    """Search for a person and list all their corporate mandates."""
    typer.echo(f"Searching mandates for: {name} ...")

    persons = asyncio.run(insee.search_by_name(name, max_results=max_results))

    if not persons:
        typer.echo("No results found.")
        raise typer.Exit()

    # Display each person and their mandates
    for p in persons:
        typer.echo(f"\n{p.full_name}")
        if not p.mandates:
            typer.echo("  (no mandates found)")
            continue

        for m in p.mandates:
            status = "active" if m.is_active else "ended"
            start = m.start_date or "?"
            end = m.end_date or "present"
            typer.echo(
                f"  [{status}] {m.role} @ {m.company.name} "
                f"({m.company.siren}) — {start} → {end}"
            )


# ---------------------------------------------------------------------------
# Command: company
# ---------------------------------------------------------------------------


@app.command()
def company(
    siren: str = typer.Argument(
        ...,
        help="9-digit SIREN number of the company",
    ),
) -> None:
    """Fetch a company by SIREN and list its directors."""
    typer.echo(f"Looking up SIREN: {siren} ...")

    comp, directors = asyncio.run(insee.search_by_siren(siren))

    # Company header
    status = "ACTIVE" if comp.active else "INACTIVE"
    typer.echo(f"\n{comp.name} ({comp.siren}) [{status}]")
    if comp.legal_form:
        typer.echo(f"  Legal form: {comp.legal_form}")
    if comp.creation_date:
        typer.echo(f"  Created: {comp.creation_date}")

    # Directors list
    typer.echo(f"\nDirectors ({len(directors)}):")
    if not directors:
        typer.echo("  (no directors found in public data)")
    for d in directors:
        for m in d.mandates:
            typer.echo(f"  - {d.full_name} — {m.role}")


# ---------------------------------------------------------------------------
# Command: cross
# ---------------------------------------------------------------------------


@app.command()
def cross(
    siren: str = typer.Argument(
        ...,
        help="9-digit SIREN of the company to investigate",
    ),
) -> None:
    """Detect shared mandate structures across a company's directors."""
    typer.echo(f"Cross-referencing mandates for SIREN: {siren} ...")

    result = asyncio.run(cross_mandates(siren))
    typer.echo(f"\n{format_cross_result(result)}")


# Allow running the CLI directly with: python -m corprecon.cli
if __name__ == "__main__":
    app()
