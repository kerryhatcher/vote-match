"""CSV reader for voter registration data."""

import pandas as pd
from loguru import logger
from pathlib import Path

# Column mapping from CSV headers to SQLAlchemy model attributes
COLUMN_MAP = {
    "Registration Number": "voter_registration_number",
    "Status": "status",
    "Last Name": "last_name",
    "First Name": "first_name",
    "Middle Name": "middle_name",
    "Name Suffix": "name_suffix",
    "Birth Year": "birth_year",
    "Race": "race",
    "Gender": "gender",
    "Street Number": "street_number",
    "Street Direction": "street_direction",
    "Street Name": "street_name",
    "Street Type": "street_type",
    "Apt/Unit #": "apt_unit",
    "City": "city",
    "Zipcode": "zipcode",
    "Mail Address Line 1": "mail_address_line_1",
    "Mail Address Line 2": "mail_address_line_2",
    "Mail Address Line 3": "mail_address_line_3",
    "Mail City": "mail_city",
    "Mail State": "mail_state",
    "Mail Zipcode": "mail_zipcode",
    "Mail Country": "mail_country",
    "County": "county",
    "County Precinct": "county_precinct",
    "Congressional District": "congressional_district",
    "State Senate District": "state_senate_district",
    "State House District": "state_house_district",
    "Judicial District": "judicial_district",
    "County Commission District": "county_commission_district",
    "School District": "school_district",
    "Municipality": "municipality",
    "Last Vote Date": "last_vote_date",
    "Last Party Voted": "last_party_voted",
    "Original Registration Date": "original_registration_date",
    "Date Changed": "date_changed",
    "Absentee Type": "absentee_type",
    "Status Reason": "status_reason",
    "Land District": "land_district",
    "Land Lot": "land_lot",
    "Residence City": "residence_city",
    "Residence Postal Code": "residence_postal_code",
    "Race Description": "race_description",
    "Precinct Split": "precinct_split",
    "Voter Status": "voter_status",
    "Street Name Full": "street_name_full",
}

# Required columns that must be present in the CSV
REQUIRED_COLUMNS = [
    "Registration Number",
    "Last Name",
    "First Name",
    "County",
    "County Precinct",
]


def read_voter_csv(file_path: str) -> pd.DataFrame:
    """
    Read voter registration CSV file.

    Args:
        file_path: Path to the CSV file

    Returns:
        pandas DataFrame with original column names

    Raises:
        FileNotFoundError: If the CSV file doesn't exist
        ValueError: If required columns are missing
    """
    path = Path(file_path)
    if not path.exists():
        logger.error("CSV file not found: {}", file_path)
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    logger.info("Reading CSV file: {}", file_path)

    # Read CSV with all columns as strings to preserve leading zeros
    df = pd.read_csv(file_path, dtype=str)

    logger.debug("CSV loaded with {} rows and {} columns", len(df), len(df.columns))

    # Validate required columns
    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        logger.error("Missing required columns: {}", missing_columns)
        raise ValueError(
            f"Missing required columns: {', '.join(missing_columns)}. "
            f"Required: {', '.join(REQUIRED_COLUMNS)}"
        )

    logger.info("CSV validation successful - all required columns present")

    return df


def dataframe_to_dicts(df: pd.DataFrame) -> list[dict]:
    """
    Convert DataFrame to list of dictionaries with renamed columns.

    Args:
        df: pandas DataFrame with CSV column names

    Returns:
        List of dictionaries with snake_case column names, ready for database insert

    Note:
        - Renames columns using COLUMN_MAP
        - Replaces pandas NaN values with None for database compatibility
        - Only includes columns that exist in COLUMN_MAP
    """
    logger.debug("Converting DataFrame to dictionaries")

    # Create a copy and rename columns
    df_mapped = df.copy()

    # Only keep columns that are in the COLUMN_MAP
    columns_to_keep = [col for col in df.columns if col in COLUMN_MAP]
    df_mapped = df_mapped[columns_to_keep]

    # Rename columns using the map
    df_mapped = df_mapped.rename(columns=COLUMN_MAP)

    # Convert to list of dictionaries and replace NaN with None
    records = df_mapped.to_dict("records")

    # Replace NaN values with None for database compatibility
    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None

    logger.debug("Converted {} records to dictionaries", len(records))

    return records
