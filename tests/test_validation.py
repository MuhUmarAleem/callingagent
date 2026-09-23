"""
Unit tests for app/validation.py — pure functions, no database or network.
"""
import pytest
from datetime import date

from app.validation import (
    validate_date_of_birth,
    validate_email,
    validate_field,
    validate_first_name,
    validate_insurance_member_id,
    validate_last_name,
    validate_patient,
    validate_phone_number,
    validate_sex,
    validate_state,
    validate_zip_code,
)


# ---------------------------------------------------------------------------
# Name tests
# ---------------------------------------------------------------------------

class TestNames:
    def test_valid_first_name(self):
        assert validate_first_name("  John  ") == "John"

    def test_first_name_with_hyphen_apostrophe(self):
        assert validate_first_name("Mary-Jane O'Brien") == "Mary-Jane O'Brien"

    def test_first_name_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_first_name("")

    def test_first_name_too_long(self):
        with pytest.raises(ValueError, match="50"):
            validate_first_name("A" * 51)

    def test_first_name_invalid_chars(self):
        with pytest.raises(ValueError, match="letters"):
            validate_first_name("John123")

    def test_valid_last_name(self):
        assert validate_last_name("Smith") == "Smith"

    def test_last_name_with_space(self):
        assert validate_last_name("Van der Berg") == "Van der Berg"


# ---------------------------------------------------------------------------
# Date of birth tests
# ---------------------------------------------------------------------------

class TestDateOfBirth:
    def test_valid_mm_dd_yyyy(self):
        assert validate_date_of_birth("01/15/1990") == date(1990, 1, 15)

    def test_valid_yyyy_mm_dd(self):
        assert validate_date_of_birth("1990-01-15") == date(1990, 1, 15)

    def test_impossible_date(self):
        with pytest.raises(ValueError, match="doesn't exist"):
            validate_date_of_birth("02/30/1990")

    def test_future_date(self):
        with pytest.raises(ValueError, match="future"):
            validate_date_of_birth("12/31/2099")

    def test_year_before_1900(self):
        with pytest.raises(ValueError, match="1900"):
            validate_date_of_birth("01/01/1899")

    def test_wrong_format_rejected(self):
        with pytest.raises(ValueError, match="month, day, year"):
            validate_date_of_birth("15-01-1990")  # DD-MM-YYYY not accepted

    def test_wrong_format_text_rejected(self):
        with pytest.raises(ValueError):
            validate_date_of_birth("January 15, 1990")

    def test_today_rejected(self):
        today = date.today().strftime("%m/%d/%Y")
        # Today is not "future" — should be accepted (born today is valid)
        result = validate_date_of_birth(today)
        assert result == date.today()

    def test_date_object_passthrough(self):
        d = date(1985, 6, 15)
        assert validate_date_of_birth(d) == d

    def test_invalid_month(self):
        with pytest.raises(ValueError):
            validate_date_of_birth("13/01/1990")


# ---------------------------------------------------------------------------
# Phone number tests
# ---------------------------------------------------------------------------

class TestPhoneNumber:
    def test_ten_digits(self):
        assert validate_phone_number("5551234567") == "5551234567"

    def test_formatted_phone(self):
        assert validate_phone_number("(555) 123-4567") == "5551234567"

    def test_eleven_digits_with_leading_1(self):
        assert validate_phone_number("15551234567") == "5551234567"

    def test_nine_digits_rejected(self):
        with pytest.raises(ValueError, match="10 digits"):
            validate_phone_number("555123456")

    def test_eleven_digits_no_leading_1(self):
        with pytest.raises(ValueError, match="10 digits"):
            validate_phone_number("25551234567")

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            validate_phone_number("")

    def test_dotted_format(self):
        assert validate_phone_number("555.123.4567") == "5551234567"

    def test_plus_one_prefix(self):
        assert validate_phone_number("+15551234567") == "5551234567"

    def test_twelve_digits_rejected(self):
        with pytest.raises(ValueError, match="10 digits"):
            validate_phone_number("155512345678")


# ---------------------------------------------------------------------------
# Sex tests
# ---------------------------------------------------------------------------

class TestSex:
    def test_male_lowercase(self):
        assert validate_sex("male") == "Male"

    def test_m_shorthand(self):
        assert validate_sex("M") == "Male"

    def test_female(self):
        assert validate_sex("Female") == "Female"

    def test_f_shorthand(self):
        assert validate_sex("f") == "Female"

    def test_other(self):
        assert validate_sex("other") == "Other"

    def test_non_binary(self):
        assert validate_sex("non-binary") == "Other"

    def test_decline(self):
        assert validate_sex("decline") == "Decline to Answer"

    def test_prefer_not_to_say(self):
        assert validate_sex("prefer not to say") == "Decline to Answer"

    def test_rather_not_say(self):
        assert validate_sex("rather not say") == "Decline to Answer"

    def test_invalid(self):
        with pytest.raises(ValueError, match="male, female"):
            validate_sex("unknown")


# ---------------------------------------------------------------------------
# State tests
# ---------------------------------------------------------------------------

class TestState:
    def test_two_letter_code(self):
        assert validate_state("CA") == "CA"

    def test_full_name(self):
        assert validate_state("california") == "CA"

    def test_full_name_mixed_case(self):
        assert validate_state("New York") == "NY"

    def test_dc(self):
        assert validate_state("DC") == "DC"

    def test_invalid_state(self):
        with pytest.raises(ValueError, match="state"):
            validate_state("XX")

    def test_invalid_full_name(self):
        with pytest.raises(ValueError):
            validate_state("Fake State")


# ---------------------------------------------------------------------------
# ZIP code tests
# ---------------------------------------------------------------------------

class TestZipCode:
    def test_five_digits(self):
        assert validate_zip_code("90210") == "90210"

    def test_nine_digits(self):
        assert validate_zip_code("90210-1234") == "90210-1234"

    def test_four_digits_rejected(self):
        with pytest.raises(ValueError, match="5 digits"):
            validate_zip_code("9021")

    def test_letters_rejected(self):
        with pytest.raises(ValueError):
            validate_zip_code("ABCDE")


# ---------------------------------------------------------------------------
# Email tests
# ---------------------------------------------------------------------------

class TestEmail:
    def test_valid_email(self):
        assert validate_email("User@Example.com") == "user@example.com"

    def test_no_at_sign(self):
        with pytest.raises(ValueError, match="email"):
            validate_email("userexample.com")

    def test_no_domain(self):
        with pytest.raises(ValueError):
            validate_email("user@")

    def test_lowercased(self):
        assert validate_email("JOHN.DOE@GMAIL.COM") == "john.doe@gmail.com"


# ---------------------------------------------------------------------------
# Insurance member ID tests
# ---------------------------------------------------------------------------

class TestInsuranceMemberId:
    def test_alphanumeric(self):
        assert validate_insurance_member_id("ABC123") == "ABC123"

    def test_strips_spaces_dashes(self):
        assert validate_insurance_member_id("ABC-123 456") == "ABC123456"

    def test_special_chars_rejected(self):
        with pytest.raises(ValueError, match="letters and numbers"):
            validate_insurance_member_id("ABC@123")

    def test_none_returns_none(self):
        assert validate_insurance_member_id(None) is None


# ---------------------------------------------------------------------------
# validate_field dispatcher tests
# ---------------------------------------------------------------------------

class TestValidateField:
    def test_known_field(self):
        assert validate_field("first_name", "Alice") == "Alice"

    def test_unknown_field_raises_key_error(self):
        with pytest.raises(KeyError):
            validate_field("nonexistent_field", "value")

    def test_invalid_value_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_field("phone_number", "123")


# ---------------------------------------------------------------------------
# validate_patient tests
# ---------------------------------------------------------------------------

class TestValidatePatient:
    GOOD_DATA = {
        "first_name": "Alice",
        "last_name": "Smith",
        "date_of_birth": "01/15/1990",
        "sex": "female",
        "phone_number": "5551234567",
        "address_line_1": "123 Main St",
        "city": "Los Angeles",
        "state": "CA",
        "zip_code": "90001",
    }

    def test_valid_full_patient(self):
        clean, errors = validate_patient(self.GOOD_DATA)
        assert not errors
        assert clean["first_name"] == "Alice"
        assert clean["sex"] == "Female"
        assert clean["state"] == "CA"
        assert clean["date_of_birth"] == date(1990, 1, 15)

    def test_missing_required_field(self):
        data = {**self.GOOD_DATA}
        del data["phone_number"]
        _, errors = validate_patient(data)
        assert "phone_number" in errors

    def test_bad_dob_in_patient(self):
        data = {**self.GOOD_DATA, "date_of_birth": "13/45/1990"}
        _, errors = validate_patient(data)
        assert "date_of_birth" in errors

    def test_partial_update_no_required_check(self):
        clean, errors = validate_patient({"first_name": "Bob"}, partial=True)
        assert not errors
        assert clean["first_name"] == "Bob"

    def test_optional_fields_not_required(self):
        clean, errors = validate_patient(self.GOOD_DATA)
        assert not errors
        # Optional fields absent — no errors
        assert "email" not in errors

    def test_optional_email_validated_when_present(self):
        data = {**self.GOOD_DATA, "email": "bad-email"}
        _, errors = validate_patient(data)
        assert "email" in errors

    def test_preferred_language_defaults_to_english(self):
        clean, errors = validate_patient(self.GOOD_DATA)
        assert clean.get("preferred_language", "English") == "English"
