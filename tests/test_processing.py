"""Tests for processing functions."""

from unittest.mock import Mock, patch

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from vote_match.processing import get_pending_voters, apply_geocode_results, process_geocoding
from vote_match.geocoder import GeocodeResult
from vote_match.models import Voter
from vote_match.config import Settings


class TestGetPendingVoters:
    """Tests for get_pending_voters function."""

    def test_get_pending_voters_only_null_status(self):
        """Test retrieving voters with NULL geocode_status."""
        # Create mock session
        session = Mock(spec=Session)
        mock_query = Mock()

        # Setup query chain
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        # Mock voters
        voter1 = Mock(spec=Voter)
        voter1.voter_registration_number = "1"
        voter1.geocode_status = None

        voter2 = Mock(spec=Voter)
        voter2.voter_registration_number = "2"
        voter2.geocode_status = None

        mock_query.all.return_value = [voter1, voter2]

        # Get pending voters
        voters = get_pending_voters(session, limit=None, retry_failed=False)

        # Verify query was made
        session.query.assert_called_once_with(Voter)
        assert len(voters) == 2

    def test_get_pending_voters_with_retry_failed(self):
        """Test retrieving voters including failed status when retry_failed=True."""
        # Create mock session
        session = Mock(spec=Session)
        mock_query = Mock()

        # Setup query chain
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        mock_query.all.return_value = []

        # Get pending voters with retry
        get_pending_voters(session, limit=None, retry_failed=True)

        # Verify filter was called (we can't easily verify the exact filter condition)
        mock_query.filter.assert_called_once()

    def test_get_pending_voters_with_limit(self):
        """Test retrieving voters with limit."""
        # Create mock session
        session = Mock(spec=Session)
        mock_query = Mock()

        # Setup query chain
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        # Get with limit
        get_pending_voters(session, limit=10, retry_failed=False)

        # Verify limit was applied
        mock_query.limit.assert_called_once_with(10)


class TestApplyGeocodeResults:
    """Tests for apply_geocode_results function."""

    def test_apply_geocode_results_matched(self):
        """Test applying geocode results for matched addresses."""
        # Create mock session
        session = Mock(spec=Session)
        mock_query = Mock()

        # Setup query chain
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        # Mock voter
        voter = Mock(spec=Voter)
        voter.voter_registration_number = "12345"
        mock_query.first.return_value = voter

        # Create geocode result
        result = GeocodeResult(
            registration_number="12345",
            status="matched",
            match_type="Exact",
            matched_address="123 MAIN ST, ATLANTA, GA, 30301",
            longitude=-84.5,
            latitude=33.5,
            tigerline_id="111",
            tigerline_side="L",
            state_fips="13",
            county_fips="121",
            tract="001500",
            block="2",
        )

        # Apply results
        updated = apply_geocode_results(session, [result])

        # Verify voter was updated
        assert voter.geocode_status == "matched"
        assert voter.geocode_match_type == "Exact"
        assert voter.geocode_matched_address == "123 MAIN ST, ATLANTA, GA, 30301"
        assert voter.geocode_longitude == -84.5
        assert voter.geocode_latitude == 33.5
        assert voter.geocode_tigerline_id == "111"
        assert voter.geocode_tigerline_side == "L"
        assert voter.geocode_state_fips == "13"
        assert voter.geocode_county_fips == "121"
        assert voter.geocode_tract == "001500"
        assert voter.geocode_block == "2"

        # Verify geometry was created
        assert voter.geom is not None
        assert isinstance(voter.geom, WKTElement)

        # Verify commit was called
        session.commit.assert_called_once()

        # Verify count
        assert updated == 1

    def test_apply_geocode_results_no_match(self):
        """Test applying geocode results for non-matched addresses."""
        # Create mock session
        session = Mock(spec=Session)
        mock_query = Mock()

        # Setup query chain
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        # Mock voter
        voter = Mock(spec=Voter)
        voter.voter_registration_number = "12345"
        mock_query.first.return_value = voter

        # Create no_match result
        result = GeocodeResult(
            registration_number="12345",
            status="no_match",
            match_type=None,
            matched_address=None,
            longitude=None,
            latitude=None,
            tigerline_id=None,
            tigerline_side=None,
            state_fips=None,
            county_fips=None,
            tract=None,
            block=None,
        )

        # Apply results
        updated = apply_geocode_results(session, [result])

        # Verify voter was updated with no_match status
        assert voter.geocode_status == "no_match"
        assert voter.geocode_longitude is None
        assert voter.geocode_latitude is None

        # Verify geometry is None
        assert voter.geom is None

        # Verify commit
        session.commit.assert_called_once()
        assert updated == 1

    def test_apply_geocode_results_voter_not_found(self):
        """Test handling when voter is not found in database."""
        # Create mock session
        session = Mock(spec=Session)
        mock_query = Mock()

        # Setup query chain to return None (voter not found)
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        # Create result
        result = GeocodeResult(
            registration_number="99999",
            status="matched",
            match_type="Exact",
            matched_address="123 MAIN ST",
            longitude=-84.5,
            latitude=33.5,
            tigerline_id="111",
            tigerline_side="L",
            state_fips="13",
            county_fips="121",
            tract="001500",
            block="2",
        )

        # Apply results
        updated = apply_geocode_results(session, [result])

        # Should skip this voter
        assert updated == 0
        session.commit.assert_called_once()


class TestProcessGeocoding:
    """Tests for process_geocoding function."""

    @patch("vote_match.processing.get_pending_voters")
    @patch("vote_match.processing.build_batch_csv")
    @patch("vote_match.processing.submit_batch")
    @patch("vote_match.processing.parse_response")
    @patch("vote_match.processing.apply_geocode_results")
    def test_process_geocoding_success(
        self,
        mock_apply,
        mock_parse,
        mock_submit,
        mock_build,
        mock_get_pending,
    ):
        """Test successful geocoding process."""
        # Mock session and settings
        session = Mock(spec=Session)
        settings = Settings()

        # Mock pending voters
        voter1 = Mock(spec=Voter)
        voter1.voter_registration_number = "1"
        voter2 = Mock(spec=Voter)
        voter2.voter_registration_number = "2"
        mock_get_pending.return_value = [voter1, voter2]

        # Mock CSV build
        mock_build.return_value = "1,addr1,city,GA,30301\n2,addr2,city,GA,30301\n"

        # Mock API response
        mock_submit.return_value = "1,addr1,Match,Exact,...\n2,addr2,No_Match,...\n"

        # Mock parsed results
        result1 = GeocodeResult(
            registration_number="1",
            status="matched",
            match_type="Exact",
            matched_address="addr1",
            longitude=-84.5,
            latitude=33.5,
            tigerline_id="111",
            tigerline_side="L",
            state_fips="13",
            county_fips="121",
            tract="001500",
            block="2",
        )
        result2 = GeocodeResult(
            registration_number="2",
            status="no_match",
            match_type=None,
            matched_address=None,
            longitude=None,
            latitude=None,
            tigerline_id=None,
            tigerline_side=None,
            state_fips=None,
            county_fips=None,
            tract=None,
            block=None,
        )
        mock_parse.return_value = [result1, result2]

        # Mock apply
        mock_apply.return_value = 2

        # Process geocoding
        stats = process_geocoding(
            session=session,
            settings=settings,
            batch_size=10000,
            limit=None,
            retry_failed=False,
        )

        # Verify stats
        assert stats["total_processed"] == 2
        assert stats["matched"] == 1
        assert stats["no_match"] == 1
        assert stats["failed"] == 0

        # Verify function calls
        mock_get_pending.assert_called_once()
        mock_build.assert_called_once()
        mock_submit.assert_called_once()
        mock_parse.assert_called_once()
        mock_apply.assert_called_once()

    @patch("vote_match.processing.get_pending_voters")
    def test_process_geocoding_no_pending_voters(self, mock_get_pending):
        """Test processing when no pending voters exist."""
        # Mock empty pending voters
        mock_get_pending.return_value = []

        session = Mock(spec=Session)
        settings = Settings()

        # Process
        stats = process_geocoding(
            session=session,
            settings=settings,
            batch_size=10000,
            limit=None,
            retry_failed=False,
        )

        # Should return zero stats
        assert stats["total_processed"] == 0
        assert stats["matched"] == 0
        assert stats["no_match"] == 0
        assert stats["failed"] == 0

    @patch("vote_match.processing.get_pending_voters")
    @patch("vote_match.processing.build_batch_csv")
    @patch("vote_match.processing.submit_batch")
    def test_process_geocoding_api_failure(
        self,
        mock_submit,
        mock_build,
        mock_get_pending,
    ):
        """Test handling of API failure."""
        # Mock session
        session = Mock(spec=Session)
        settings = Settings()

        # Mock pending voters
        voter1 = Mock(spec=Voter)
        voter1.voter_registration_number = "1"
        voter1.geocode_status = None
        mock_get_pending.return_value = [voter1]

        # Mock CSV build
        mock_build.return_value = "1,addr,city,GA,30301\n"

        # Mock API failure
        mock_submit.side_effect = Exception("API Error")

        # Process (should not raise exception)
        stats = process_geocoding(
            session=session,
            settings=settings,
            batch_size=10000,
            limit=None,
            retry_failed=False,
        )

        # Voter should be marked as failed
        assert voter1.geocode_status == "failed"
        assert stats["total_processed"] == 1
        assert stats["failed"] == 1

    @patch("vote_match.processing.get_pending_voters")
    def test_process_geocoding_batch_size_limit(self, mock_get_pending):
        """Test that batch size is limited to 10000."""
        session = Mock(spec=Session)
        settings = Settings()

        # Create large list of voters
        voters = [Mock(spec=Voter) for _ in range(15000)]
        for i, voter in enumerate(voters):
            voter.voter_registration_number = str(i)
        mock_get_pending.return_value = voters

        # Process with large batch size (should be clamped to 10000)
        with patch("vote_match.processing.build_batch_csv") as mock_build:
            with patch("vote_match.processing.submit_batch") as mock_submit:
                with patch("vote_match.processing.parse_response") as mock_parse:
                    with patch("vote_match.processing.apply_geocode_results") as mock_apply:
                        # Mock returns
                        mock_build.return_value = "csv"
                        mock_submit.return_value = "response"
                        mock_parse.return_value = []
                        mock_apply.return_value = 0

                        # Process with batch size > 10000
                        process_geocoding(
                            session=session,
                            settings=settings,
                            batch_size=15000,
                            limit=None,
                            retry_failed=False,
                        )

                        # Should be called twice (10000 + 5000)
                        assert mock_build.call_count == 2
