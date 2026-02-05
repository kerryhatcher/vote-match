"""SQLAlchemy models for Vote Match application."""

from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class GeocodeResult(Base):
    """Stores geocoding results from any service.

    This table supports multiple geocoding services by storing results
    separately for each service. Each voter can have multiple results
    from different services, and the best result is determined dynamically.
    """

    __tablename__ = "geocode_results"

    id = Column(Integer, primary_key=True)
    voter_id = Column(
        String,
        ForeignKey("voters.voter_registration_number"),
        nullable=False,
        index=True,
    )
    service_name = Column(String(50), nullable=False, index=True)
    status = Column(
        String(20), nullable=False
    )  # exact, interpolated, approximate, no_match, failed
    longitude = Column(Float, nullable=True)
    latitude = Column(Float, nullable=True)
    matched_address = Column(Text, nullable=True)
    match_confidence = Column(Float, nullable=True)  # 0.0-1.0
    raw_response = Column(JSON, nullable=True)  # Service-specific data
    error_message = Column(Text, nullable=True)
    geocoded_at = Column(DateTime, nullable=False, default=func.now())

    # Relationship
    voter = relationship("Voter", back_populates="geocode_results")

    # Composite index for efficient queries
    __table_args__ = (
        Index("idx_geocode_results_voter_service", "voter_id", "service_name"),
        Index("idx_geocode_results_status", "status"),
    )

    def __repr__(self) -> str:
        """String representation of GeocodeResult model."""
        return (
            f"<GeocodeResult(voter_id='{self.voter_id}', "
            f"service='{self.service_name}', "
            f"status='{self.status}')>"
        )


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

    # District comparison results (added by compare-districts command)
    spatial_district_id = Column(String(10), nullable=True, index=True)
    spatial_district_name = Column(String(100), nullable=True)
    district_mismatch = Column(Boolean, nullable=True, index=True)
    district_compared_at = Column(DateTime, nullable=True)

    # USPS validation result fields (added by USPS validator)
    usps_validation_status = Column(String, nullable=True, index=True)
    usps_validated_street_address = Column(String, nullable=True)
    usps_validated_city = Column(String, nullable=True)
    usps_validated_state = Column(String, nullable=True)
    usps_validated_zipcode = Column(String, nullable=True)
    usps_validated_zipplus4 = Column(String, nullable=True)
    usps_delivery_point = Column(String, nullable=True)
    usps_carrier_route = Column(String, nullable=True)
    usps_dpv_confirmation = Column(String, nullable=True)
    usps_business = Column(String, nullable=True)
    usps_vacant = Column(String, nullable=True)

    # Relationships
    geocode_results = relationship(
        "GeocodeResult",
        back_populates="voter",
        order_by="GeocodeResult.geocoded_at.desc()",
    )

    # Additional indexes
    __table_args__ = (
        Index("idx_voter_geocode_status", "geocode_status"),
        Index("idx_voter_county", "county"),
        Index("idx_voter_county_precinct", "county_precinct"),
        Index("idx_voter_usps_validation", "usps_validation_status"),
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

    @property
    def best_geocode_result(self) -> Optional["GeocodeResult"]:
        """Returns highest quality geocode result across all services.

        Priority: exact > interpolated > approximate > no_match > failed
        Within same quality, prefer higher confidence score.

        Returns:
            Best GeocodeResult or None if no results exist
        """
        if not self.geocode_results:
            return None

        quality_order = ["exact", "interpolated", "approximate", "no_match", "failed"]

        def sort_key(result: "GeocodeResult") -> tuple[int, float]:
            """Sort key: (quality_rank, -confidence)."""
            try:
                quality_rank = quality_order.index(result.status)
            except ValueError:
                quality_rank = len(quality_order)  # Unknown statuses go last

            confidence = result.match_confidence if result.match_confidence else 0.0
            return (quality_rank, -confidence)

        sorted_results = sorted(self.geocode_results, key=sort_key)
        return sorted_results[0]

    @property
    def needs_geocoding(self) -> bool:
        """Check if voter needs geocoding.

        Returns True if:
        - No geocoding results exist at all
        - Best result is no_match or failed

        Returns:
            True if geocoding is needed
        """
        best = self.best_geocode_result
        return best is None or best.status in ["no_match", "failed"]

    @property
    def has_successful_geocode(self) -> bool:
        """Check if voter has at least one successful geocode.

        Returns:
            True if best result is exact, interpolated, or approximate
        """
        best = self.best_geocode_result
        return best is not None and best.status in [
            "exact",
            "interpolated",
            "approximate",
        ]

    def __repr__(self) -> str:
        """String representation of Voter model."""
        return (
            f"<Voter(voter_registration_number='{self.voter_registration_number}', "
            f"name='{self.first_name} {self.last_name}', "
            f"geocode_status='{self.geocode_status}')>"
        )


class CountyCommissionDistrict(Base):
    """Electoral district boundaries for spatial analysis.

    This model stores district boundary polygons and metadata imported from
    GeoJSON files. Used for comparing voter registration districts with their
    actual geocoded locations via spatial joins.
    """

    __tablename__ = "county_commission_districts"

    id = Column(Integer, primary_key=True)

    # Core district identification fields (NOT NULL)
    district_id = Column(String(10), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)

    # Representative information (nullable - some districts may be vacant)
    rep_name = Column(String(100), nullable=True)
    party = Column(String(50), nullable=True)
    district_url = Column(String(255), nullable=True)
    email = Column(String(100), nullable=True)
    photo_url = Column(String(255), nullable=True)
    rep_name_2 = Column(String(100), nullable=True)

    # Metadata (nullable - may not always be present in source data)
    object_id = Column(Integer, nullable=True)
    global_id = Column(String(100), nullable=True)
    creation_date = Column(DateTime, nullable=True)
    creator = Column(String(100), nullable=True)
    edit_date = Column(DateTime, nullable=True)
    editor = Column(String(100), nullable=True)

    # PostGIS geometry column (NOT NULL - districts must have boundaries)
    # Using POLYGON (not MULTIPOLYGON) based on GeoJSON inspection
    geom = Column(Geometry("POLYGON", srid=4326), nullable=False)

    # Indexes for spatial and text queries
    __table_args__ = (
        Index("idx_district_geom", "geom", postgresql_using="gist"),
        Index("idx_district_name", "name"),
    )

    def __repr__(self) -> str:
        """String representation of CountyCommissionDistrict model."""
        return f"<CountyCommissionDistrict(district_id='{self.district_id}', name='{self.name}')>"
