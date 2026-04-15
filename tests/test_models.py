"""
Tests for Pydantic models (Company, Person, Mandate).

These tests validate:
- Model creation with valid data
- Validation constraints (SIREN format, required fields)
- Computed properties (is_active, full_name, active_mandates)
"""

from datetime import date

import pytest
from pydantic import ValidationError

from corprecon.models import Company, Mandate, Person


# ---------------------------------------------------------------------------
# Company tests
# ---------------------------------------------------------------------------


class TestCompany:
    """Tests for the Company model."""

    def test_valid_company(self):
        """A company with all required fields should be created."""
        c = Company(siren="123456789", name="Acme SAS")
        assert c.siren == "123456789"
        assert c.name == "Acme SAS"
        assert c.active is True  # default

    def test_siren_must_be_9_digits(self):
        """SIREN must be exactly 9 digits — anything else is rejected."""
        with pytest.raises(ValidationError):
            Company(siren="12345", name="Too Short")

        with pytest.raises(ValidationError):
            Company(siren="1234567890", name="Too Long")

        with pytest.raises(ValidationError):
            Company(siren="ABCDEFGHI", name="Not Digits")

    def test_optional_fields(self):
        """Optional fields should default to None."""
        c = Company(siren="123456789", name="Test")
        assert c.legal_form is None
        assert c.creation_date is None

    def test_full_company(self):
        """Company with all fields populated."""
        c = Company(
            siren="987654321",
            name="Big Corp SA",
            legal_form="5710",
            active=False,
            creation_date=date(2020, 1, 15),
        )
        assert c.active is False
        assert c.legal_form == "5710"
        assert c.creation_date == date(2020, 1, 15)


# ---------------------------------------------------------------------------
# Mandate tests
# ---------------------------------------------------------------------------


class TestMandate:
    """Tests for the Mandate model and its is_active property."""

    @pytest.fixture
    def company(self) -> Company:
        """A reusable test company."""
        return Company(siren="111222333", name="Test SARL")

    def test_active_mandate(self, company):
        """A mandate with no end_date is considered active."""
        m = Mandate(role="Gérant", company=company)
        assert m.is_active is True

    def test_ended_mandate(self, company):
        """A mandate with an end_date is considered inactive."""
        m = Mandate(
            role="Président",
            company=company,
            start_date=date(2020, 1, 1),
            end_date=date(2023, 6, 30),
        )
        assert m.is_active is False

    def test_mandate_with_start_only(self, company):
        """A mandate with start_date but no end_date is still active."""
        m = Mandate(
            role="Administrateur",
            company=company,
            start_date=date(2021, 3, 15),
        )
        assert m.is_active is True


# ---------------------------------------------------------------------------
# Person tests
# ---------------------------------------------------------------------------


class TestPerson:
    """Tests for the Person model and its computed properties."""

    @pytest.fixture
    def company_a(self) -> Company:
        return Company(siren="111111111", name="Company A")

    @pytest.fixture
    def company_b(self) -> Company:
        return Company(siren="222222222", name="Company B")

    def test_full_name_with_first_and_last(self):
        """full_name returns 'First Last' when both are present."""
        p = Person(first_name="Victor", last_name="Pacoud")
        assert p.full_name == "Victor Pacoud"

    def test_full_name_last_only(self):
        """full_name returns just the last name when no first name."""
        p = Person(last_name="Holding XYZ")
        assert p.full_name == "Holding XYZ"

    def test_active_mandates_filter(self, company_a, company_b):
        """active_mandates should only return mandates without end_date."""
        p = Person(
            first_name="Alice",
            last_name="Dupont",
            mandates=[
                # Active mandate (no end date)
                Mandate(role="Gérante", company=company_a),
                # Ended mandate
                Mandate(
                    role="Présidente",
                    company=company_b,
                    end_date=date(2022, 12, 31),
                ),
            ],
        )
        active = p.active_mandates
        assert len(active) == 1
        assert active[0].company.siren == "111111111"

    def test_empty_mandates(self):
        """A person with no mandates should have empty lists."""
        p = Person(last_name="Nobody")
        assert p.mandates == []
        assert p.active_mandates == []
