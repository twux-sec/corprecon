"""
Tests for the cross-detection logic (crosser.py).

These tests use mocked INSEE API responses so we can test the logic
without needing a real API token or network access.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from corprecon.crosser import CrossResult, cross_mandates, format_cross_result
from corprecon.models import Company, Mandate, Person


# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------


@pytest.fixture
def company_target() -> Company:
    """The company being investigated."""
    return Company(siren="100000001", name="Target SAS", active=True)


@pytest.fixture
def company_shared() -> Company:
    """A company that multiple directors share."""
    return Company(siren="200000002", name="Shared SARL", active=True)


@pytest.fixture
def company_unrelated() -> Company:
    """A company with no overlap."""
    return Company(siren="300000003", name="Solo Corp", active=True)


@pytest.fixture
def director_alice(company_target, company_shared) -> Person:
    """Alice — director of both Target and Shared."""
    return Person(
        first_name="Alice",
        last_name="Dupont",
        mandates=[
            Mandate(role="Présidente", company=company_target),
            Mandate(role="Gérante", company=company_shared),
        ],
    )


@pytest.fixture
def director_bob(company_target, company_shared, company_unrelated) -> Person:
    """Bob — director of Target, Shared AND an unrelated company."""
    return Person(
        first_name="Bob",
        last_name="Martin",
        mandates=[
            Mandate(role="Gérant", company=company_target),
            Mandate(role="Administrateur", company=company_shared),
            Mandate(role="Président", company=company_unrelated),
        ],
    )


# ---------------------------------------------------------------------------
# CrossResult tests
# ---------------------------------------------------------------------------


class TestCrossResult:
    """Tests for the CrossResult dataclass and its properties."""

    def test_shared_companies_filters_correctly(
        self, company_target, company_shared, director_alice, director_bob
    ):
        """
        shared_companies should only return companies where 2+ directors
        from the target appear — and exclude the target itself.
        """
        result = CrossResult(
            target=company_target,
            directors=[director_alice, director_bob],
            shared={
                # Target itself (should be excluded)
                "100000001": [
                    (director_alice, director_alice.mandates[0]),
                    (director_bob, director_bob.mandates[0]),
                ],
                # Shared company (Alice + Bob → should be included)
                "200000002": [
                    (director_alice, director_alice.mandates[1]),
                    (director_bob, director_bob.mandates[1]),
                ],
                # Solo company (only Bob → should be excluded, < 2 persons)
                "300000003": [
                    (director_bob, director_bob.mandates[2]),
                ],
            },
        )

        shared = result.shared_companies
        # Only the shared company should appear
        assert "200000002" in shared
        assert "100000001" not in shared  # target excluded
        assert "300000003" not in shared  # only 1 director

    def test_no_shared_companies(self, company_target):
        """When no overlap exists, shared_companies is empty."""
        result = CrossResult(target=company_target, directors=[], shared={})
        assert result.shared_companies == {}


# ---------------------------------------------------------------------------
# format_cross_result tests
# ---------------------------------------------------------------------------


class TestFormatCrossResult:
    """Tests for the human-readable output formatter."""

    def test_format_includes_company_name(self, company_target):
        """The output should contain the target company's name and SIREN."""
        result = CrossResult(target=company_target)
        output = format_cross_result(result)
        assert "Target SAS" in output
        assert "100000001" in output

    def test_format_shows_no_shared_message(self, company_target):
        """When no shared structures exist, show a clear message."""
        result = CrossResult(target=company_target)
        output = format_cross_result(result)
        assert "No shared structures detected" in output

    def test_format_shows_shared_structures(
        self, company_target, company_shared, director_alice, director_bob
    ):
        """When shared structures exist, list them with linked directors."""
        result = CrossResult(
            target=company_target,
            directors=[director_alice, director_bob],
            shared={
                "200000002": [
                    (director_alice, director_alice.mandates[1]),
                    (director_bob, director_bob.mandates[1]),
                ],
            },
        )
        output = format_cross_result(result)
        assert "Shared structures (1)" in output
        assert "Shared SARL" in output
        assert "Alice Dupont" in output
        assert "Bob Martin" in output


# ---------------------------------------------------------------------------
# cross_mandates integration test (with mocked API)
# ---------------------------------------------------------------------------


class TestCrossMandates:
    """Test the full cross_mandates pipeline with mocked INSEE calls."""

    @pytest.mark.asyncio
    async def test_cross_mandates_pipeline(
        self, company_target, company_shared, director_alice, director_bob
    ):
        """
        Mock the INSEE API and verify the full pipeline:
        1. search_by_siren returns target + directors
        2. search_by_name returns each director's other mandates
        3. The result correctly identifies shared structures
        """
        # Mock search_by_siren to return our target company and 2 directors
        mock_siren = AsyncMock(
            return_value=(
                company_target,
                [
                    # Directors returned by INSEE (with only target mandate)
                    Person(
                        first_name="Alice",
                        last_name="Dupont",
                        mandates=[
                            Mandate(role="Présidente", company=company_target)
                        ],
                    ),
                    Person(
                        first_name="Bob",
                        last_name="Martin",
                        mandates=[
                            Mandate(role="Gérant", company=company_target)
                        ],
                    ),
                ],
            )
        )

        # Mock search_by_name to return additional mandates for each director
        async def mock_name_search(name, **kwargs):
            if "Dupont" in name:
                return [
                    Person(
                        first_name="Alice",
                        last_name="Dupont",
                        mandates=[
                            Mandate(role="Gérante", company=company_shared),
                        ],
                    )
                ]
            elif "Martin" in name:
                return [
                    Person(
                        first_name="Bob",
                        last_name="Martin",
                        mandates=[
                            Mandate(
                                role="Administrateur", company=company_shared
                            ),
                        ],
                    )
                ]
            return []

        with (
            patch(
                "corprecon.crosser.insee.search_by_siren", mock_siren
            ),
            patch(
                "corprecon.crosser.insee.search_by_name",
                side_effect=mock_name_search,
            ),
            patch("corprecon.crosser.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await cross_mandates("100000001")

        assert result.target.siren == "100000001"
        assert len(result.directors) == 2
        # Both Alice and Bob have mandates at the shared company
        assert "200000002" in result.shared
