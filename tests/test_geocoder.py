"""Tests for geocoding functionality."""

import pytest
from unittest.mock import Mock, patch

from vote_match.geocoder import GeocodeResult, build_batch_csv, parse_response, submit_batch
from vote_match.models import Voter
from vote_match.config import Settings


class TestBuildBatchCsv:
    """Tests for build_batch_csv function."""

    def test_build_batch_csv_with_complete_addresses(self):
        """Test building CSV with complete voter addresses."""
        # Create mock voters
        voter1 = Mock(spec=Voter)
        voter1.voter_registration_number = "17913041"
        voter1.build_street_address.return_value = "1090 KING ARTHUR DR"
        voter1.residence_city = "MACON"
        voter1.residence_zipcode = "31220"

        voter2 = Mock(spec=Voter)
        voter2.voter_registration_number = "18086952"
        voter2.build_street_address.return_value = "104 WEBSTER CT"
        voter2.residence_city = "MACON"
        voter2.residence_zipcode = "31220"

        voters = [voter1, voter2]

        # Build CSV
        csv_content = build_batch_csv(voters)

        # Verify format
        lines = csv_content.strip().split("\n")
        assert len(lines) == 2

        assert lines[0] == '17913041,"1090 KING ARTHUR DR",MACON,GA,31220'
        assert lines[1] == '18086952,"104 WEBSTER CT",MACON,GA,31220'

    def test_build_batch_csv_skips_incomplete_addresses(self):
        """Test that voters with missing address fields are skipped."""
        # Voter with missing city
        voter1 = Mock(spec=Voter)
        voter1.voter_registration_number = "1"
        voter1.build_street_address.return_value = "123 MAIN ST"
        voter1.residence_city = None
        voter1.residence_zipcode = "30301"

        # Voter with missing street
        voter2 = Mock(spec=Voter)
        voter2.voter_registration_number = "2"
        voter2.build_street_address.return_value = ""
        voter2.residence_city = "ATLANTA"
        voter2.residence_zipcode = "30301"

        # Complete voter
        voter3 = Mock(spec=Voter)
        voter3.voter_registration_number = "3"
        voter3.build_street_address.return_value = "456 OAK AVE"
        voter3.residence_city = "ATLANTA"
        voter3.residence_zipcode = "30301"

        voters = [voter1, voter2, voter3]

        # Build CSV
        csv_content = build_batch_csv(voters)

        # Only the complete voter should be included
        lines = csv_content.strip().split("\n")
        assert len(lines) == 1
        assert "3" in lines[0]
        assert "456 OAK AVE" in lines[0]

    def test_build_batch_csv_empty_list(self):
        """Test building CSV with empty voter list."""
        csv_content = build_batch_csv([])
        assert csv_content == ""


class TestParseResponse:
    """Tests for parse_response function."""

    def test_parse_response_with_match(self):
        """Test parsing response with successful geocode match."""
        response_text = (
            '17913041,"1090 KING ARTHUR DR, MACON, GA, 31220",Match,Exact,'
            '"1090 KING ARTHUR DR, MACON, GA, 31220","(-83.123456, 32.654321)",'
            '12345678,L,13,021,001500,2\n'
        )

        results = parse_response(response_text)

        assert len(results) == 1
        result = results[0]

        assert result.registration_number == "17913041"
        assert result.status == "matched"
        assert result.match_type == "Exact"
        assert result.matched_address == "1090 KING ARTHUR DR, MACON, GA, 31220"
        assert result.longitude == -83.123456
        assert result.latitude == 32.654321
        assert result.tigerline_id == "12345678"
        assert result.tigerline_side == "L"
        assert result.state_fips == "13"
        assert result.county_fips == "021"
        assert result.tract == "001500"
        assert result.block == "2"

    def test_parse_response_with_no_match(self):
        """Test parsing response with no geocode match."""
        response_text = '18086952,"104 WEBSTER CT, MACON, GA, 31220",No_Match,,,,,,,,,\n'

        results = parse_response(response_text)

        assert len(results) == 1
        result = results[0]

        assert result.registration_number == "18086952"
        assert result.status == "no_match"
        assert result.match_type is None
        assert result.matched_address is None
        assert result.longitude is None
        assert result.latitude is None
        assert result.tigerline_id is None

    def test_parse_response_with_tie(self):
        """Test parsing response with tie (multiple matches)."""
        response_text = (
            '12345678,"123 MAIN ST, ATLANTA, GA, 30301",Tie,Exact,'
            '"123 MAIN ST, ATLANTA, GA, 30301","(-84.5, 33.5)",'
            '11111111,R,13,121,002000,1\n'
        )

        results = parse_response(response_text)

        assert len(results) == 1
        result = results[0]

        # Tie should be treated as matched
        assert result.status == "matched"
        assert result.longitude == -84.5
        assert result.latitude == 33.5

    def test_parse_response_multiple_records(self):
        """Test parsing response with multiple records."""
        response_text = (
            '1,"ADDR1, CITY, GA, 12345",Match,Exact,"ADDR1, CITY, GA, 12345",'
            '"(-83.0, 32.0)",111,L,13,021,001500,2\n'
            '2,"ADDR2, CITY, GA, 12345",No_Match,,,,,,,,,\n'
            '3,"ADDR3, CITY, GA, 12345",Match,Non_Exact,"ADDR3 CORRECTED, CITY, GA, 12345",'
            '"(-83.1, 32.1)",222,R,13,021,001600,3\n'
        )

        results = parse_response(response_text)

        assert len(results) == 3
        assert results[0].status == "matched"
        assert results[1].status == "no_match"
        assert results[2].status == "matched"
        assert results[2].match_type == "Non_Exact"

    def test_parse_response_malformed_coordinates(self):
        """Test parsing response with malformed coordinates."""
        response_text = (
            '12345,"ADDR, CITY, GA, 12345",Match,Exact,"ADDR, CITY, GA, 12345",'
            '"(invalid)",111,L,13,021,001500,2\n'
        )

        results = parse_response(response_text)

        assert len(results) == 1
        result = results[0]

        # Should still create result but with None coordinates
        assert result.status == "matched"
        assert result.longitude is None
        assert result.latitude is None

    def test_parse_response_empty_string(self):
        """Test parsing empty response."""
        results = parse_response("")
        assert len(results) == 0


class TestSubmitBatch:
    """Tests for submit_batch function."""

    @patch('vote_match.geocoder.httpx.Client')
    def test_submit_batch_success(self, mock_client_class):
        """Test successful batch submission to Census API."""
        # Mock response
        mock_response = Mock()
        mock_response.text = "1,addr,Match,Exact,matched_addr,coords,111,L,13,021,001500,2\n"
        mock_response.raise_for_status = Mock()

        # Mock client
        mock_client = Mock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        # Create settings
        settings = Settings(
            census_benchmark="Public_AR_Current",
            census_vintage="Current_Current",
            census_timeout=300,
        )

        # Submit batch
        csv_content = "1,123 MAIN ST,ATLANTA,GA,30301\n"
        response_text = submit_batch(csv_content, settings)

        # Verify API call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        assert call_args[0][0] == "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
        assert call_args[1]['data']['benchmark'] == "Public_AR_Current"
        assert call_args[1]['data']['vintage'] == "Current_Current"

        # Verify response
        assert response_text == mock_response.text

    @patch('vote_match.geocoder.httpx.Client')
    def test_submit_batch_http_error(self, mock_client_class):
        """Test handling of HTTP errors."""
        # Mock error response
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("HTTP Error")

        # Mock client
        mock_client = Mock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        settings = Settings()
        csv_content = "1,123 MAIN ST,ATLANTA,GA,30301\n"

        # Should raise exception
        with pytest.raises(Exception):
            submit_batch(csv_content, settings)

    @patch('vote_match.geocoder.httpx.Client')
    def test_submit_batch_timeout(self, mock_client_class):
        """Test handling of timeout errors."""
        import httpx

        # Mock client that times out
        mock_client = Mock()
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        settings = Settings(census_timeout=10)
        csv_content = "1,123 MAIN ST,ATLANTA,GA,30301\n"

        # Should raise TimeoutException
        with pytest.raises(httpx.TimeoutException):
            submit_batch(csv_content, settings)
