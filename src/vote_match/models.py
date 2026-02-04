"""SQLAlchemy models for Vote Match application."""

from sqlalchemy import Column, Float, Index, String
from sqlalchemy.orm import declarative_base
from geoalchemy2 import Geometry

Base = declarative_base()


class Voter(Base):
    """Voter registration record with geocoding results."""

    __tablename__ = "voters"

    # Primary key (from CSV "Registration Number")
    voter_registration_number = Column(String, primary_key=True)

    # All 47 CSV columns (stored as String to preserve leading zeros)
    status = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    middle_name = Column(String, nullable=True)
    name_suffix = Column(String, nullable=True)
    birth_year = Column(String, nullable=True)
    race = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    street_number = Column(String, nullable=True)
    street_direction = Column(String, nullable=True)
    street_name = Column(String, nullable=True)
    street_type = Column(String, nullable=True)
    apt_unit = Column(String, nullable=True)  # from "Apt/Unit #"
    city = Column(String, nullable=True)
    zipcode = Column(String, nullable=True)
    mail_address_line_1 = Column(String, nullable=True)
    mail_address_line_2 = Column(String, nullable=True)
    mail_address_line_3 = Column(String, nullable=True)
    mail_city = Column(String, nullable=True)
    mail_state = Column(String, nullable=True)
    mail_zipcode = Column(String, nullable=True)
    mail_country = Column(String, nullable=True)
    county = Column(String, nullable=True)
    county_precinct = Column(String, nullable=True)
    congressional_district = Column(String, nullable=True)
    state_senate_district = Column(String, nullable=True)
    state_house_district = Column(String, nullable=True)
    judicial_district = Column(String, nullable=True)
    county_commission_district = Column(String, nullable=True)
    school_district = Column(String, nullable=True)
    municipality = Column(String, nullable=True)
    last_vote_date = Column(String, nullable=True)
    last_party_voted = Column(String, nullable=True)
    original_registration_date = Column(String, nullable=True)
    date_changed = Column(String, nullable=True)
    absentee_type = Column(String, nullable=True)
    status_reason = Column(String, nullable=True)
    land_district = Column(String, nullable=True)
    land_lot = Column(String, nullable=True)
    residence_city = Column(String, nullable=True)
    residence_postal_code = Column(String, nullable=True)
    race_description = Column(String, nullable=True)
    precinct_split = Column(String, nullable=True)
    voter_status = Column(String, nullable=True)
    street_name_full = Column(String, nullable=True)

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
            Full street address (e.g., "123 N Main St Apt 5")
        """
        components = []

        # Street number
        if self.street_number:
            components.append(self.street_number)

        # Street direction
        if self.street_direction:
            components.append(self.street_direction)

        # Street name
        if self.street_name:
            components.append(self.street_name)

        # Street type
        if self.street_type:
            components.append(self.street_type)

        # Apartment/Unit
        if self.apt_unit:
            components.append(f"Apt {self.apt_unit}")

        return " ".join(components)

    def __repr__(self) -> str:
        """String representation of Voter model."""
        return (
            f"<Voter(voter_registration_number='{self.voter_registration_number}', "
            f"name='{self.first_name} {self.last_name}', "
            f"geocode_status='{self.geocode_status}')>"
        )
