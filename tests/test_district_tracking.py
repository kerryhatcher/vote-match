"""Tests for district tracking functionality.

Tests cover:
- import_district_boundaries(): GeoJSON import, property detection, duplicates
- compare_all_districts(): spatial joins, mismatch classification
- _save_district_assignments(): upsert behavior
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from sqlalchemy.orm import Session

from vote_match.processing import (
    import_district_boundaries,
    compare_all_districts,
    _save_district_assignments,
)


# ========== FIXTURES ==========


@pytest.fixture
def sample_geojson_file(tmp_path: Path) -> Path:
    """Create a sample GeoJSON file with 2 district boundaries."""
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "DISTRICT": "1",
                    "NAME": "District 1",
                    "REPNAME1": "John Doe",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-84.5, 33.5],
                            [-84.5, 33.6],
                            [-84.4, 33.6],
                            [-84.4, 33.5],
                            [-84.5, 33.5],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"DISTRICT": "2", "NAME": "District 2"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-84.4, 33.5],
                            [-84.4, 33.6],
                            [-84.3, 33.6],
                            [-84.3, 33.5],
                            [-84.4, 33.5],
                        ]
                    ],
                },
            },
        ],
    }

    file_path = tmp_path / "districts.geojson"
    with open(file_path, "w") as f:
        json.dump(geojson_data, f)
    return file_path


# ========== TEST CLASSES ==========


class TestImportDistrictBoundaries:
    """Tests for import_district_boundaries function."""

    def test_import_invalid_district_type(self, sample_geojson_file: Path):
        """Test that invalid district type raises ValueError."""
        session = Mock(spec=Session)

        with pytest.raises(ValueError, match="Unknown district type"):
            import_district_boundaries(
                session=session,
                file_path=sample_geojson_file,
                district_type="invalid_type",
            )

    def test_import_file_not_found(self):
        """Test that missing file raises FileNotFoundError."""
        session = Mock(spec=Session)
        nonexistent = Path("/nonexistent/file.geojson")

        with pytest.raises(FileNotFoundError):
            import_district_boundaries(
                session=session,
                file_path=nonexistent,
                district_type="congressional",
            )

    def test_import_geojson_success(self, sample_geojson_file: Path):
        """Test successful import of GeoJSON district boundaries."""
        session = Mock(spec=Session)
        mock_query = Mock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []  # No existing IDs

        result = import_district_boundaries(
            session=session,
            file_path=sample_geojson_file,
            district_type="congressional",
            clear_existing=False,
        )

        # Verify results
        assert result["total"] == 2
        assert result["success"] == 2
        assert result["failed"] == 0
        assert result["skipped"] == 0

        # Verify session.add was called twice
        assert session.add.call_count == 2
        session.commit.assert_called()

    def test_import_duplicate_skipped(self, sample_geojson_file: Path):
        """Test that duplicate district IDs are skipped."""
        session = Mock(spec=Session)
        mock_query = Mock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = [("1",)]  # District "1" exists

        result = import_district_boundaries(
            session=session,
            file_path=sample_geojson_file,
            district_type="congressional",
        )

        assert result["skipped"] == 1
        assert result["success"] == 1


class TestCompareAllDistricts:
    """Tests for compare_all_districts function."""

    def test_compare_no_boundaries(self):
        """Test comparison when no boundaries exist."""
        session = Mock(spec=Session)
        mock_query = Mock()
        session.query.return_value = mock_query
        mock_query.distinct.return_value = mock_query
        mock_query.all.return_value = []  # No boundaries

        result = compare_all_districts(session)

        assert result == {}

    def test_compare_single_district_type(self):
        """Test comparison for a single district type."""
        session = Mock(spec=Session)

        # Mock available types query
        mock_query = Mock()
        session.query.return_value = mock_query
        mock_query.distinct.return_value = mock_query
        mock_query.all.return_value = [("congressional",)]

        # Mock spatial join results
        mock_execute = Mock()
        session.execute.return_value = mock_execute
        mock_execute.fetchall.return_value = [
            ("V001", "14", "14", "District 14"),  # Match
            ("V002", "14", "15", "District 15"),  # Mismatch
            ("V003", "14", None, None),  # No district
            ("V004", None, "14", "District 14"),  # No registered
        ]

        result = compare_all_districts(
            session=session,
            district_types=["congressional"],
            save_to_db=False,
        )

        assert "congressional" in result
        stats = result["congressional"]
        assert stats["total"] == 4
        assert stats["matched"] == 1
        assert stats["mismatched"] == 1
        assert stats["no_district"] == 1
        assert stats["no_registered"] == 1

    def test_compare_with_limit(self):
        """Test that limit parameter is applied to SQL query."""
        session = Mock(spec=Session)

        mock_query = Mock()
        session.query.return_value = mock_query
        mock_query.distinct.return_value = mock_query
        mock_query.all.return_value = [("congressional",)]

        mock_execute = Mock()
        session.execute.return_value = mock_execute
        mock_execute.fetchall.return_value = []

        compare_all_districts(
            session=session,
            district_types=["congressional"],
            limit=100,
        )

        # Verify SQL contains LIMIT parameter
        call_args = session.execute.call_args
        assert "limit" in str(call_args).lower()


class TestSaveDistrictAssignments:
    """Tests for _save_district_assignments function."""

    def test_save_assignments_upsert(self):
        """Test that upsert logic works correctly."""
        session = Mock(spec=Session)

        assignments = [
            {
                "voter_id": "VOTER001",
                "district_type": "congressional",
                "registered_value": "14",
                "spatial_district_id": "14",
                "spatial_district_name": "District 14",
                "is_mismatch": False,
                "compared_at": datetime.now(),
            }
        ]

        _save_district_assignments(
            session=session,
            district_type="congressional",
            assignments=assignments,
        )

        # Verify execute and commit were called
        session.execute.assert_called_once()
        session.commit.assert_called_once()

    def test_save_assignments_batching(self):
        """Test that large assignment lists are batched."""
        session = Mock(spec=Session)

        # Create 2500 assignments (should be 3 batches of 1000)
        assignments = [
            {
                "voter_id": f"VOTER{i:06d}",
                "district_type": "congressional",
                "registered_value": "14",
                "spatial_district_id": "14",
                "spatial_district_name": "District 14",
                "is_mismatch": False,
                "compared_at": datetime.now(),
            }
            for i in range(2500)
        ]

        _save_district_assignments(
            session=session,
            district_type="congressional",
            assignments=assignments,
        )

        # Verify execute was called 3 times (3 batches)
        assert session.execute.call_count == 3
        session.commit.assert_called_once()
