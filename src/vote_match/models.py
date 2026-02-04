"""SQLAlchemy models for Vote Match application."""

from sqlalchemy import Column, Float, Index, String
from sqlalchemy.orm import declarative_base
from geoalchemy2 import Geometry

Base = declarative_base()


class Voter(Base):
    """Voter registration record with geocoding results."""

    __tablename__ = "voters"

    # Primary key (from CSV "Voter Registration Number")
    voter_registration_number = Column(String, primary_key=True)

    # All 53 CSV columns (stored as String to preserve leading zeros)
    # Basic Information
    county = Column(String, nullable=True)
    status = Column(String, nullable=True)
    status_reason = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    middle_name = Column(String, nullable=True)
    suffix = Column(String, nullable=True)
    birth_year = Column(String, nullable=True)

    # Residence Address
    residence_street_number = Column(String, nullable=True)
    residence_pre_direction = Column(String, nullable=True)
    residence_street_name = Column(String, nullable=True)
    residence_street_type = Column(String, nullable=True)
    residence_post_direction = Column(String, nullable=True)
    residence_apt_unit_number = Column(String, nullable=True)
    residence_city = Column(String, nullable=True)
    residence_zipcode = Column(String, nullable=True)

    # Precinct Information
    county_precinct = Column(String, nullable=True)
    county_precinct_description = Column(String, nullable=True)
    municipal_precinct = Column(String, nullable=True)
    municipal_precinct_description = Column(String, nullable=True)

    # Districts
    congressional_district = Column(String, nullable=True)
    state_senate_district = Column(String, nullable=True)
    state_house_district = Column(String, nullable=True)
    judicial_district = Column(String, nullable=True)
    county_commission_district = Column(String, nullable=True)
    school_board_district = Column(String, nullable=True)
    city_council_district = Column(String, nullable=True)
    municipal_school_board_district = Column(String, nullable=True)
    water_board_district = Column(String, nullable=True)
    super_council_district = Column(String, nullable=True)
    super_commissioner_district = Column(String, nullable=True)
    super_school_board_district = Column(String, nullable=True)
    fire_district = Column(String, nullable=True)

    # Municipality and Land Information
    municipality = Column(String, nullable=True)
    combo = Column(String, nullable=True)
    land_lot = Column(String, nullable=True)
    land_district = Column(String, nullable=True)

    # Registration and Voting History
    registration_date = Column(String, nullable=True)
    race = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    last_modified_date = Column(String, nullable=True)
    date_of_last_contact = Column(String, nullable=True)
    last_party_voted = Column(String, nullable=True)
    last_vote_date = Column(String, nullable=True)
    voter_created_date = Column(String, nullable=True)

    # Mailing Address
    mailing_street_number = Column(String, nullable=True)
    mailing_street_name = Column(String, nullable=True)
    mailing_apt_unit_number = Column(String, nullable=True)
    mailing_city = Column(String, nullable=True)
    mailing_zipcode = Column(String, nullable=True)
    mailing_state = Column(String, nullable=True)
    mailing_country = Column(String, nullable=True)

    # Geocoding result fields (added by geocoder)
    geocode_status = Column(String, nullable=True, index=True)
    geocode_match_type = Column(String, nullable=True)
    geocode_matched_address = Column(String, nullable=True)
    geocode_longitude = Column(Float, nullable=True)
    geocode_latitude = Column(Float, nullable=True)
    geocode_tigerline_id = Column(String, nullable=True)
    geocode_tigerline_side = Column(String, nullable=True)
    geocode_state_fips = Column(String, nullable=True)
    geocode_county_fips = Column(String, nullable=True)
    geocode_tract = Column(String, nullable=True)
    geocode_block = Column(String, nullable=True)

    # PostGIS geometry column (populated from geocode lat/lon)
    geom = Column(Geometry("POINT", srid=4326), nullable=True)

    # Additional indexes
    __table_args__ = (
        Index("idx_voter_geocode_status", "geocode_status"),
        Index("idx_voter_county", "county"),
        Index("idx_voter_county_precinct", "county_precinct"),
    )

    def build_street_address(self) -> str:
        """
        Construct full street address from components for geocoding.

        Returns:
            Full street address (e.g., "123 N Main St SE Apt 5")
        """
        components = []

        # Street number
        if self.residence_street_number:
            components.append(self.residence_street_number)

        # Pre direction
        if self.residence_pre_direction:
            components.append(self.residence_pre_direction)

        # Street name
        if self.residence_street_name:
            components.append(self.residence_street_name)

        # Street type
        if self.residence_street_type:
            components.append(self.residence_street_type)

        # Post direction
        if self.residence_post_direction:
            components.append(self.residence_post_direction)

        # Apartment/Unit
        if self.residence_apt_unit_number:
            components.append(f"Apt {self.residence_apt_unit_number}")

        return " ".join(components)

    def __repr__(self) -> str:
        """String representation of Voter model."""
        return (
            f"<Voter(voter_registration_number='{self.voter_registration_number}', "
            f"name='{self.first_name} {self.last_name}', "
            f"geocode_status='{self.geocode_status}')>"
        )
