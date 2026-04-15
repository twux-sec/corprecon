# CorpRecon

> OSINT tool to map French corporate mandate networks from public data.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/github/license/twux-sec/corprecon)
![Topics](https://img.shields.io/badge/topics-osint%20%7C%20corpint%20%7C%20finint-orange)

CorpRecon investigates French companies and their directors using public registers (INSEE SIRENE, BODACC, Pappers). Given a person's name or a SIREN number, it maps all corporate mandates and detects shared structures where multiple directors overlap — a common pattern in holding networks and related-party schemes.

## Features

- **Person lookup** — find all corporate mandates held by a person (active and past)
- **Company lookup** — list all directors of a company by SIREN number
- **Cross-detection** — identify shared structures where multiple directors of a company also co-appear
- **Async & rate-limited** — respects INSEE API limits, uses async HTTP for performance
- **Clean data models** — Pydantic v2 models with validation and computed properties

## Installation

```bash
git clone https://github.com/twux-sec/corprecon.git
cd corprecon
pip install -e .
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
```

## Configuration

Get a free INSEE SIRENE API token at [api.insee.fr](https://api.insee.fr), then:

```bash
cp .env.example .env
# Edit .env and paste your token
```

## Quickstart

```bash
# Search all mandates for a person
corprecon person "Jean Dupont"

# Look up a company by SIREN
corprecon company 913234567

# Cross-reference: detect shared structures across directors
corprecon cross 913234567
```

## Architecture

```
corprecon/
├── cli.py              # Typer CLI — person, company, cross commands
├── models.py           # Pydantic models: Company, Person, Mandate
├── crosser.py          # Cross-detection logic (shared structures)
└── sources/
    ├── insee.py         # INSEE SIRENE V3 async wrapper
    ├── pappers.py       # (V1.5) Pappers API wrapper
    └── bodacc.py        # (V2) BODACC announcements
```

## Roadmap

- [x] **V1** — INSEE SIRENE integration, person/company/cross commands, tests
- [ ] **V1.5** — Pappers API integration (richer director data)
- [ ] **V2** — NetworkX relationship graph + GraphML export for Gephi

## Designed by

Designed by [@twux-sec](https://github.com/twux-sec).
Implementation assisted by Claude AI (Anthropic) — code reviewed, tested and integrated by the author.

## Legal & ethical use

- **GDPR compliant** — CorpRecon only queries publicly available data published in official French registers (RCS, INSEE SIRENE, BODACC).
- **Public sources only** — no scraping of social media, no access to private or restricted databases.
- **No targeting of private individuals** outside of a legal framework.
- **Intended use cases**: research, journalism, financial due diligence, and authorized investigations only.

## License

[MIT](LICENSE) — Twux

## Contact

GitHub: [@twux-sec](https://github.com/twux-sec)
