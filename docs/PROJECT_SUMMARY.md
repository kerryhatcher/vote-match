# Vote Match: Voter-District Mismatch Analysis for Macon-Bibb County

## Context for Blog Post Authors

This document provides the full background, motivation, methodology, and technical details of the Vote Match project. Use it as source material to write a narrative blog post about the project.

---

## Purpose

Vote Match is an open-source Python tool that compares voter registration records against official county commission district boundaries to identify mismatches -- voters whose registered district (per the Georgia Secretary of State) does not match the district they physically reside in (per the county's own GIS district map).

The project's primary output was a finding that **at least 540 voters in Macon-Bibb County, Georgia were registered in District 5 according to the Secretary of State, but do not reside in District 5 according to Macon-Bibb County's own GIS district boundaries.** The total number of mismatched voters across all districts grew to **1,035** as the analysis was refined.

The findings, along with interactive maps and CSV data, were shared directly with county officials (Mr. Gillon and Ms. Evans) and the underlying code was published publicly on GitHub.

---

## Why This Was Done

### The Trigger

At a Macon-Bibb County Commission meeting in early 2026, **Commissioner Bryant raised concerns about the accuracy of the county's district maps**. Kerry Hatcher, a Macon-Bibb County resident and software engineer, heard those concerns and began investigating independently.

### The Urgency

Macon-Bibb County had an **upcoming special election**, which made the accuracy of district assignments critically important. If voters were assigned to the wrong district, they could be voting for the wrong commissioner -- a fundamental issue of representation. Kerry noted in his initial email to county officials:

> "Normally, I would prefer to do some double checking, verification, and separate analysis before bringing this to your attention. However, I think the upcoming special election calls for urgency."

### The Finding

Kerry's analysis identified a minimum of 540 voters registered in District 5 per the Secretary of State who do not reside in District 5 per Macon-Bibb County GIS boundaries. He described his expectation that the final number would "only increase (if at all)" as low-confidence geocodes were resolved. The final count across all nine districts reached 1,035 mismatched voters.

### What Was Shared With Officials

1. **February 4, 2026 (morning)**: Initial email to Mr. Gillon and Ms. Evans with the 540-voter finding, a QGIS-generated map (attached as "District 5 Errors.pdf"), an explanation of methodology, and links to source data (voter roll on Google Drive) and source code (GitHub).

2. **February 4-7, 2026**: Continued development of the tool, culminating in an interactive web map hosted at a private URL (`maps.kerryhatcher.com`) with 1,035 total mismatched voters, along with a CSV export of the data. The source code remained publicly available on GitHub throughout.

Kerry offered full transparency: *"I'm more than happy to share my source data and work, as well as collaborate with MBC GIS (or anyone) to independently verify the data."*

---

## How It Was Done

### Methodology (Plain Language)

1. **Obtained the voter roll**: Downloaded a recent Macon-Bibb County voter registration file from the Georgia Secretary of State. This file contains each voter's name, address, and -- critically -- their assigned districts (county commission, congressional, state senate, state house, etc.).

2. **Obtained the district map**: Downloaded the current county commission district boundary shapefile from Macon-Bibb County's own GIS system. This is the official map that defines where each of the 9 commission districts begins and ends.

3. **Geocoded voter addresses**: Converted each voter's street address into geographic coordinates (latitude/longitude) using multiple geocoding services, starting with the free US Census Batch Geocoder and falling back to other services for addresses that didn't match.

4. **Stored everything in a spatial database**: Loaded both the voter coordinates and the district boundary polygons into a PostGIS database (PostgreSQL with spatial extensions).

5. **Performed a spatial join**: For each voter point, determined which district polygon it falls within. This gives the voter's "spatial district" -- the district they actually live in according to the map.

6. **Compared registered vs. spatial district**: Compared each voter's Secretary of State district assignment against the spatially-determined district. Any voter where these don't match is a "mismatch."

7. **Filtered for confidence**: Removed low-confidence geocodes (approximate or failed matches) to produce a conservative minimum count of mismatches.

8. **Generated visualizations**: Created interactive Leaflet web maps color-coded by district, with clustered markers for the mismatched voters, overlaid on the district boundary polygons. Also exported CSV files for further analysis.

### Development Timeline

The entire tool was built over **4 days** (February 4-7, 2026) in **50 commits**:

- **Feb 4 (morning)**: Initial codebase with voter CSV loading, database schema, Census geocoding, USPS validation, and core processing pipeline. First email sent to officials with 540-voter finding.
- **Feb 4 (afternoon)**: Added multi-service geocoding architecture (Nominatim, Mapbox, Geocodio, Photon, Google Maps), district boundary import from GeoJSON, spatial comparison logic, interactive Leaflet map generation, and Cloudflare R2 upload for hosting maps. Follow-up email sent with interactive map URL and CSV.
- **Feb 5**: Refined export filters, mobile UI improvements, credit information updates.
- **Feb 6**: Added PII redaction option for public-facing maps, improved map credit display.
- **Feb 7**: Added HTML iframe embed code generation for sharing maps.

---

## Technical Overview

### Architecture

Vote Match is a **Python 3.13+ CLI application** built with:

- **Typer** for the command-line interface
- **SQLAlchemy 2.0** as the ORM
- **PostgreSQL + PostGIS** for spatial data storage and queries
- **Alembic** for database migrations
- **Jinja2** for HTML map template rendering
- **Leaflet.js** for interactive web maps
- **Cloudflare R2** (S3-compatible) for map hosting
- **UV** for Python package and environment management

### Key Data Flow

```
Voter CSV (GA SOS) ──► load-csv ──► Voter Table (PostGIS)
                                          │
                                          ▼
                                    geocode (Census, Nominatim, etc.)
                                          │
                                          ▼
                                    GeocodeResult Table
                                          │
                                          ▼
                                    sync-geocode (best result → Voter.geom)
                                          │
                                          ▼
District GeoJSON (MBC GIS) ──► import-geojson ──► CountyCommissionDistrict Table
                                                        │
                                                        ▼
                                                  compare-districts
                                                  (ST_Within spatial join)
                                                        │
                                                        ▼
                                              Mismatch Results (CSV, Map)
                                                        │
                                                        ▼
                                              export --format leaflet
                                              --upload-to-r2
                                                        │
                                                        ▼
                                              Interactive Web Map (Cloudflare R2)
```

### Database Schema

Three tables in PostGIS:

1. **`voters`** -- One row per voter registration record. Contains name, address components, all district assignments from the SOS file, geocoding results, PostGIS POINT geometry (`geom`), and spatial comparison results (`spatial_district_id`, `district_mismatch`).

2. **`geocode_results`** -- One row per voter per geocoding service. Stores the result from each service independently so the system can select the best result. Indexed on `(voter_id, service_name)`.

3. **`county_commission_districts`** -- One row per district. Stores the district boundary as a PostGIS POLYGON geometry with a GiST spatial index, plus metadata (representative names, party, contact info).

### Multi-Service Geocoding

The system uses a cascading strategy across 6 geocoding services:

| Service | Type | Cost | Coverage | Batch Size |
|---------|------|------|----------|------------|
| Census | Batch | Free | US only | 10,000 |
| Geocodio | Batch | Paid | US/Canada | 10,000 |
| Mapbox | Batch | Paid | Global | 1,000 |
| Nominatim | Individual | Free | Global | 1/sec |
| Photon | Individual | Free | Global | 1/sec |
| Google Maps | Individual | Paid | Global | 1/req |

Each service implements a common interface (`GeocodeService` base class) with three methods: `prepare_addresses()`, `submit_request()`, and `parse_response()`. Services are registered via a decorator-based registry pattern. Results are normalized into a `StandardGeocodeResult` dataclass with a quality enum: `EXACT > INTERPOLATED > APPROXIMATE > NO_MATCH > FAILED`.

The cascading logic: Census runs first on all voters. Subsequent services only process voters whose best existing result is `NO_MATCH` or `FAILED`. The `sync-geocode` command then selects each voter's highest-quality result across all services and writes it to the `geom` column.

### Spatial Join (The Core Analysis)

The district comparison uses a single PostGIS query:

```sql
SELECT v.*, d.district_id, d.name
FROM voters v
LEFT JOIN county_commission_districts d
  ON ST_Within(v.geom, d.geom)
WHERE v.geom IS NOT NULL
```

This determines which district polygon each voter point falls within. The result is compared against the voter's `county_commission_district` field from the SOS file. Mismatches are flagged with `district_mismatch = true` and can be filtered, exported, or mapped.

### Interactive Map Generation

The `export --format leaflet` command generates a self-contained web folder:

```
web/
├── index.html                      # Leaflet map with clustering
├── voters.<hash>.geojson           # Voter points as GeoJSON
└── districts.<hash>.geojson        # District polygons as GeoJSON
```

The map uses **Leaflet.js** with the **MarkerCluster** plugin. Voters are color-coded by district (9 distinct colors matching the district map). District boundaries are displayed as colored polygon overlays. The map supports clustering at far zoom levels that dissolves into individual labeled markers as you zoom in. Filenames include content hashes for cache-busting.

Maps are optionally uploaded to **Cloudflare R2** (S3-compatible object storage) and served via a public URL with an obscured folder path for access control.

### Privacy Controls

The `--redact-pii` flag strips voter names, specific addresses, and registration numbers from the exported GeoJSON, leaving only district assignments and geocode quality indicators. This allows sharing maps publicly without exposing individual voter information.

### CLI Commands (Full List)

| Command | Purpose |
|---------|---------|
| `init-db` | Initialize PostGIS database and run migrations |
| `load-csv <file>` | Import voter registration CSV |
| `geocode --service <name>` | Geocode addresses with specified service |
| `sync-geocode` | Write best geocode results to Voter geometry column |
| `delete-geocode-results` | Remove geocode results for retry |
| `validate-usps` | Validate addresses via USPS API |
| `import-geojson <file>` | Import district boundaries from GeoJSON |
| `compare-districts` | Spatial join to find district mismatches |
| `export <file>` | Export to CSV, GeoJSON, or interactive Leaflet map |
| `status` | Show geocoding/validation statistics |
| `db-migrate` | Generate Alembic migration from model changes |
| `db-upgrade` | Apply database migrations |
| `db-downgrade` | Rollback database migrations |
| `db-current` | Show current migration revision |
| `db-history` | List migration history |
| `db-stamp` | Stamp database at a revision without running migrations |

---

## Key Numbers

- **1,035** total voters with district mismatches identified
- **540** initial mismatch count (District 5 alone, conservative estimate)
- **9** county commission districts analyzed
- **6** geocoding services supported
- **50** commits over 4 days of development
- **~16,000 lines** of code (including tests, templates, and lock files)

---

## Source Materials

- **Source code**: https://github.com/kerryhatcher/vote-match
- **Interactive map** (shared with officials): `https://maps.kerryhatcher.com/304rhjgh02u6667gskrsdthjw84rgh/mbc.html`
- **Voter roll source**: Georgia Secretary of State voter registration file for Macon-Bibb County
- **District boundaries source**: Macon-Bibb County GIS
- **License**: AGPL-3.0 (open source)

---

## Narrative Themes for Blog Post

1. **Citizen-driven accountability**: A private citizen used publicly available data and open-source tools to independently verify government records, then shared findings transparently with officials.

2. **Urgency vs. thoroughness**: Kerry explicitly noted the tension between wanting to verify further and the pressing timeline of the upcoming special election.

3. **Transparency as a feature**: Every piece of the analysis -- the code, the data sources, the methodology -- was shared openly. The tool itself was published on GitHub.

4. **Technical accessibility**: The core question ("are voters in the right district?") is simple. The answer required combining voter data, geocoding, spatial databases, and GIS analysis -- but the tool automates the entire pipeline into a few CLI commands.

5. **Scale of the finding**: 1,035 voters is not trivial. In local elections where margins can be thin, having over a thousand voters potentially assigned to the wrong district has real consequences for representation.

6. **The maps tell the story**: The QGIS screenshots and interactive Leaflet map make the abstract data concrete -- you can see exactly which voters are in the wrong district and where they actually live.
