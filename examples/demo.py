"""
Demo script — shows expected usage of CorpRecon.

Run with: python examples/demo.py
Requires: INSEE_TOKEN set in .env (or mock mode for testing).
"""

from corprecon.cli import app

if __name__ == "__main__":
    # Launch the CLI — same as running `corprecon` from the terminal
    app()
