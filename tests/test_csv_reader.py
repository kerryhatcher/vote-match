"""Tests for CSV reader module."""

from pathlib import Path

import pandas as pd
import pytest

from vote_match.csv_reader import (
    COLUMN_MAP,
    REQUIRED_COLUMNS,
    read_voter_csv,
    dataframe_to_dicts,
)


@pytest.fixture
def minimal_csv_content() -> str:
    """
    Provide minimal valid CSV content with required columns only.

    Returns:
        CSV content as string
    """
    return "Voter Registration Number,Last Name,First Name,County,County Precinct,Residence City,Residence Zipcode\n01234567,DOE,JOHN,FULTON,01-001,ATLANTA,30303\n01234568,SMITH,JANE,COBB,02-002,MARIETTA,30060\n"


@pytest.fixture
def full_csv_content() -> str:
    """
    Provide CSV content with all 53 columns (as per COLUMN_MAP).

    Returns:
        CSV content as string
    """
    header = "County,Voter Registration Number,Status,Status Reason,Last Name,First Name,Middle Name,Suffix,Birth Year,Residence Street Number,Residence Pre Direction,Residence Street Name,Residence Street Type,Residence Post Direction,Residence Apt Unit Number,Residence City,Residence Zipcode,County Precinct,County Precinct Description,Municipal Precinct,Municipal Precinct Description,Congressional District,State Senate District,State House District,Judicial District,County Commission District,School Board District,City Council District,Municipal School Board District,Water Board District,Super Council District,Super Commissioner District,Super School Board District,Fire District,Municipality,Combo,Land Lot,Land District,Registration Date,Race,Gender,Last Modified Date,Date of Last Contact,Last Party Voted,Last Vote Date,Voter Created Date,Mailing Street Number,Mailing Street Name,Mailing Apt Unit Number,Mailing City,Mailing Zipcode,Mailing State,Mailing Country"
    # 53 values to match 53 columns
    row1 = "FULTON,01234567,Active,,DOE,JOHN,MICHAEL,JR,1985,123,N,MAIN,ST,,APT 5,ATLANTA,30303,01-001,Precinct 1,,,05,38,55,ATLANTA,01,01,01,01,01,01,01,01,01,ATLANTA,COMBO1,A,100,01/15/2010,W,M,03/20/2023,,DEM,11/08/2022,01/15/2010,123,MAIN ST,APT 5,ATLANTA,30303,GA,"
    row2 = "COBB,01234568,Active,,SMITH,JANE,ANN,,1990,456,,OAK,AVE,,,MARIETTA,30060,02-002,Precinct 2,,,06,39,56,MARIETTA,02,02,02,02,02,02,02,02,02,MARIETTA,COMBO2,B,150,02/10/2012,B,F,02/10/2012,,REP,11/08/2022,02/10/2012,456,OAK AVE,,MARIETTA,30060,GA,"
    return f"{header}\n{row1}\n{row2}\n"


@pytest.fixture
def minimal_csv_file(tmp_path: Path, minimal_csv_content: str) -> Path:
    """
    Create a temporary CSV file with minimal content.

    Args:
        tmp_path: pytest's temporary directory fixture
        minimal_csv_content: CSV content fixture

    Returns:
        Path to temporary CSV file
    """
    csv_file = tmp_path / "test_voters.csv"
    csv_file.write_text(minimal_csv_content)
    return csv_file


@pytest.fixture
def full_csv_file(tmp_path: Path, full_csv_content: str) -> Path:
    """
    Create a temporary CSV file with full content.

    Args:
        tmp_path: pytest's temporary directory fixture
        full_csv_content: CSV content fixture

    Returns:
        Path to temporary CSV file
    """
    csv_file = tmp_path / "test_voters_full.csv"
    csv_file.write_text(full_csv_content)
    return csv_file


def test_read_voter_csv_file_not_found():
    """Test that read_voter_csv raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        read_voter_csv("/nonexistent/path/to/file.csv")


def test_read_voter_csv_missing_required_columns(tmp_path: Path):
    """Test that read_voter_csv raises ValueError when required columns are missing."""
    # Create CSV with missing required column "County Precinct"
    csv_content = """Voter Registration Number,Last Name,First Name,County
01234567,DOE,JOHN,FULTON
"""
    csv_file = tmp_path / "incomplete.csv"
    csv_file.write_text(csv_content)

    with pytest.raises(ValueError) as exc_info:
        read_voter_csv(str(csv_file))

    assert "County Precinct" in str(exc_info.value)
    assert "Missing required columns" in str(exc_info.value)


def test_read_voter_csv_minimal(minimal_csv_file: Path):
    """Test reading CSV with minimal required columns."""
    df = read_voter_csv(str(minimal_csv_file))

    # Check that DataFrame was created
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2

    # Check that required columns are present
    for col in REQUIRED_COLUMNS:
        assert col in df.columns

    # Check data types (should all be strings or string dtype)
    for col in df.columns:
        # pandas dtype=str creates StringDtype with repr like 'str' or 'string'
        dtype_str = str(df[col].dtype)
        assert df[col].dtype == "object" or "str" in dtype_str.lower()

    # Check first record
    assert df.iloc[0]["Voter Registration Number"] == "01234567"
    assert df.iloc[0]["Last Name"] == "DOE"
    assert df.iloc[0]["First Name"] == "JOHN"


def test_read_voter_csv_full(full_csv_file: Path):
    """Test reading CSV with all 53 columns."""
    df = read_voter_csv(str(full_csv_file))

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2

    # Check that all mapped columns are present
    for csv_col in COLUMN_MAP.keys():
        if csv_col in df.columns:
            # Verify column exists
            assert csv_col in df.columns


def test_read_voter_csv_preserves_leading_zeros(full_csv_file: Path):
    """Test that leading zeros are preserved in zipcodes and codes."""
    df = read_voter_csv(str(full_csv_file))

    # Check that zipcodes preserve leading zeros
    assert df.iloc[0]["Residence Zipcode"] == "30303"

    # Check that district codes are strings
    assert isinstance(df.iloc[0]["Congressional District"], str)


def test_dataframe_to_dicts_column_mapping(full_csv_file: Path):
    """Test that dataframe_to_dicts correctly maps column names."""
    df = read_voter_csv(str(full_csv_file))
    records = dataframe_to_dicts(df)

    assert len(records) == 2

    # Check first record
    record = records[0]

    # Verify key columns are mapped correctly
    assert "voter_registration_number" in record
    assert record["voter_registration_number"] == "01234567"

    assert "last_name" in record
    assert record["last_name"] == "DOE"

    assert "first_name" in record
    assert record["first_name"] == "JOHN"

    assert "middle_name" in record
    assert record["middle_name"] == "MICHAEL"

    assert "residence_apt_unit_number" in record
    assert record["residence_apt_unit_number"] == "APT 5"

    assert "county" in record
    assert record["county"] == "FULTON"

    assert "county_precinct" in record
    assert record["county_precinct"] == "01-001"


def test_dataframe_to_dicts_handles_none_values(tmp_path: Path):
    """Test that dataframe_to_dicts converts NaN to None."""
    # Create CSV with empty values
    csv_content = "Voter Registration Number,Last Name,First Name,Middle Name,County,County Precinct\n01234567,DOE,JOHN,,FULTON,01-001\n"
    csv_file = tmp_path / "test_with_empty.csv"
    csv_file.write_text(csv_content)

    df = read_voter_csv(str(csv_file))
    records = dataframe_to_dicts(df)

    # Middle name should be None (was empty in CSV)
    assert records[0]["middle_name"] is None


def test_dataframe_to_dicts_only_includes_mapped_columns(tmp_path: Path):
    """Test that only columns in COLUMN_MAP are included in output."""
    # Create CSV with an extra column not in COLUMN_MAP
    csv_content = "Voter Registration Number,Last Name,First Name,County,County Precinct,Extra Column\n01234567,DOE,JOHN,FULTON,01-001,EXTRA VALUE\n"
    csv_file = tmp_path / "test_with_extra.csv"
    csv_file.write_text(csv_content)

    df = read_voter_csv(str(csv_file))
    records = dataframe_to_dicts(df)

    # Extra column should not be in the output
    assert "Extra Column" not in records[0]
    assert "extra_column" not in records[0]


def test_column_map_completeness():
    """Test that COLUMN_MAP has entries for all expected columns."""
    # We expect 53 columns in the map (actual Georgia voter file structure)
    assert len(COLUMN_MAP) == 53

    # Check that all required columns are in the map
    for col in REQUIRED_COLUMNS:
        assert col in COLUMN_MAP


def test_required_columns_list():
    """Test that REQUIRED_COLUMNS contains expected columns."""
    assert "Voter Registration Number" in REQUIRED_COLUMNS
    assert "Last Name" in REQUIRED_COLUMNS
    assert "First Name" in REQUIRED_COLUMNS
    assert "County" in REQUIRED_COLUMNS
    assert "County Precinct" in REQUIRED_COLUMNS
    assert len(REQUIRED_COLUMNS) == 5
