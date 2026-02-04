"""CSV reader for voter registration data."""

import pandas as pd
from loguru import logger
from pathlib import Path

# Column mapping from CSV headers to SQLAlchemy model attributes
# Maps all 53 columns from the Georgia voter file
COLUMN_MAP = {
    # Basic Information (columns 1-9)
    "County": "county",
    "Voter Registration Number": "voter_registration_number",
    "Status": "status",
    "Status Reason": "status_reason",
    "Last Name": "last_name",
    "First Name": "first_name",
    "Middle Name": "middle_name",
    "Suffix": "suffix",
    "Birth Year": "birth_year",
    # Residence Address (columns 10-17)
    "Residence Street Number": "residence_street_number",
    "Residence Pre Direction": "residence_pre_direction",
    "Residence Street Name": "residence_street_name",
    "Residence Street Type": "residence_street_type",
    "Residence Post Direction": "residence_post_direction",
    "Residence Apt Unit Number": "residence_apt_unit_number",
    "Residence City": "residence_city",
    "Residence Zipcode": "residence_zipcode",
    # Precinct Information (columns 18-21)
    "County Precinct": "county_precinct",
    "County Precinct Description": "county_precinct_description",
    "Municipal Precinct": "municipal_precinct",
    "Municipal Precinct Description": "municipal_precinct_description",
    # Districts (columns 22-34)
    "Congressional District": "congressional_district",
    "State Senate District": "state_senate_district",
    "State House District": "state_house_district",
    "Judicial District": "judicial_district",
    "County Commission District": "county_commission_district",
    "School Board District": "school_board_district",
    "City Council District": "city_council_district",
    "Municipal School Board District": "municipal_school_board_district",
    "Water Board District": "water_board_district",
    "Super Council District": "super_council_district",
    "Super Commissioner District": "super_commissioner_district",
    "Super School Board District": "super_school_board_district",
    "Fire District": "fire_district",
    # Municipality and Land Information (columns 35-38)
    "Municipality": "municipality",
    "Combo": "combo",
    "Land Lot": "land_lot",
    "Land District": "land_district",
    # Registration and Voting History (columns 39-46)
    "Registration Date": "registration_date",
    "Race": "race",
    "Gender": "gender",
    "Last Modified Date": "last_modified_date",
    "Date of Last Contact": "date_of_last_contact",
    "Last Party Voted": "last_party_voted",
    "Last Vote Date": "last_vote_date",
    "Voter Created Date": "voter_created_date",
    # Mailing Address (columns 47-53)
    "Mailing Street Number": "mailing_street_number",
    "Mailing Street Name": "mailing_street_name",
    "Mailing Apt Unit Number": "mailing_apt_unit_number",
    "Mailing City": "mailing_city",
    "Mailing Zipcode": "mailing_zipcode",
    "Mailing State": "mailing_state",
    "Mailing Country": "mailing_country",
}

# Required columns that must be present in the CSV
REQUIRED_COLUMNS = [
    "Voter Registration Number",
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
