# CLI README Best Practices

A comprehensive guide to writing excellent README.md files for command-line interface (CLI) applications, synthesized from industry best practices and community standards.

## Table of Contents

- [Overview](#overview)
- [Essential Sections](#essential-sections)
- [Structure and Organization](#structure-and-organization)
- [Installation and Setup](#installation-and-setup)
- [Usage Documentation](#usage-documentation)
- [Examples and Code Samples](#examples-and-code-samples)
- [Configuration and Environment](#configuration-and-environment)
- [CLI-Specific Best Practices](#cli-specific-best-practices)
- [Accessibility Considerations](#accessibility-considerations)
- [Visual Elements](#visual-elements)
- [Maintenance and Updates](#maintenance-and-updates)

---

## Overview

A README for a CLI tool serves multiple critical purposes:
- **First Impression**: It's the entry point for potential users and contributors
- **Documentation**: Explains what the tool does and how to use it
- **Marketing**: Makes your tool stand out and encourages adoption
- **Support**: Reduces support requests by answering common questions upfront

**Golden Rules:**
1. Optimize for humans first, machines second
2. Keep it concise but comprehensive
3. Show, don't just tell (use examples liberally)
4. Make it scannable with clear headings
5. Keep information current and accurate

---

## Essential Sections

### 1. Project Title and Description

**What to Include:**
- Clear, memorable project name
- One-line description of what it does
- Brief explanation of the problem it solves
- Key features or differentiators

**Example:**
```markdown
# vote-match

A Python CLI tool for processing voter registration records for GIS applications.

Streamlines the workflow of converting voter records from CSV to PostGIS, geocoding addresses, and matching voters to precincts with spatial joins.

**Key Features:**
- Multi-service geocoding support (Census, Nominatim, etc.)
- Automatic syncing of best geocoding results
- QGIS-ready spatial data output
- Alembic-managed database migrations
```

### 2. Table of Contents

For README files longer than a few screens, include a clickable table of contents:

```markdown
## Table of Contents
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Examples](#examples)
- [Contributing](#contributing)
- [License](#license)
```

### 3. Installation

**Best Practices:**
- Provide multiple installation methods when applicable
- List prerequisites clearly
- Include platform-specific instructions if needed
- Provide single-command installation where possible

**Example:**
```markdown
## Installation

### Prerequisites
- Python 3.13+
- PostGIS-enabled PostgreSQL database
- uv (Python package manager)

### Install via uv
```bash
uv add vote-match
```

### Build from source
```bash
git clone https://github.com/yourusername/vote-match.git
cd vote-match
uv sync
```
```

### 4. Quick Start

Provide the fastest path to a working example:

```markdown
## Quick Start

1. Initialize the database:
   ```bash
   vote-match init-db
   ```

2. Load voter data:
   ```bash
   vote-match load-csv sample.csv
   ```

3. Geocode addresses:
   ```bash
   vote-match geocode --service census
   ```

4. Sync results for QGIS:
   ```bash
   vote-match sync-geocode
   ```
```

### 5. Commands and Usage

**CLI-Specific Requirements:**
- Document all commands and subcommands
- Show available flags and options
- Indicate required vs. optional parameters
- Explain what each command does

**Example:**
```markdown
## Commands

### Database Management

#### `vote-match init-db`
Initialize the PostGIS database schema.

#### `vote-match db-migrate -m "message"`
Create a new Alembic migration.
- `-m, --message` (required): Migration description

### Data Import

#### `vote-match load-csv <file>`
Import voter registration CSV file.
- `<file>` (required): Path to CSV file

Options:
- `--batch-size`: Number of records per batch (default: 1000)

### Geocoding

#### `vote-match geocode --service <name>`
Geocode voter addresses using specified service.

Options:
- `--service`: Geocoding service (census, nominatim) [required]
- `--reprocess`: Re-geocode existing results
- `--limit`: Maximum records to process
```

### 6. Configuration

**Document:**
- Configuration file locations (follow XDG spec when applicable)
- Environment variables
- Command-line flags
- Precedence order

**Example:**
```markdown
## Configuration

### Configuration File
`~/.config/vote-match/config.yaml`

### Environment Variables

- `VOTE_MATCH_DB_URL`: Database connection string
- `VOTE_MATCH_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `NO_COLOR`: Disable colored output

### Precedence
1. Command-line flags (highest priority)
2. Environment variables
3. Configuration file
4. Built-in defaults (lowest priority)
```

### 7. Examples

**Best Practices:**
- Provide real-world usage examples
- Show common workflows end-to-end
- Include expected output where helpful
- Cover edge cases and advanced usage

### 8. Contributing

```markdown
## Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes and add tests
4. Run linting and tests
5. Commit using [Conventional Commits](https://www.conventionalcommits.org/)
6. Push to your fork
7. Open a Pull Request
```

### 9. License

```markdown
## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
```

---

## Structure and Organization

### Markdown Best Practices

```markdown
# Use hierarchical headers (H1 for title, H2 for main sections)

## Main Section

### Subsection

**Bold for emphasis** and *italics for subtle emphasis*.

`Inline code for commands and filenames`

```bash
# Code blocks with syntax highlighting
command --flag value
```

- Bullet points for lists
- Use blank lines between sections

> **Note:** Use blockquotes for important callouts
```

### Information Hierarchy

**Organize by priority:**
1. **What** it is (title, description)
2. **Why** use it (motivation, features)
3. **How** to get started (installation, quick start)
4. **How** to use it (commands, examples)
5. **How** to configure it (configuration)
6. **How** to contribute (development, contributing)
7. **Additional information** (license, credits, FAQ)

---

## Installation and Setup

### Best Practices

**Prerequisites:**
- List system requirements explicitly
- Specify version requirements
- Include external dependencies
- Platform-specific requirements

**Multiple Installation Methods:**
```markdown
## Installation

### Option 1: Package Manager (Recommended)
```bash
# Homebrew (macOS/Linux)
brew install vote-match

# apt (Debian/Ubuntu)
sudo apt install vote-match
```

### Option 2: Python Package
```bash
uv add vote-match
```

### Option 3: Build from Source
```bash
git clone https://github.com/user/vote-match.git
cd vote-match
make install
```
```

**Post-Installation Verification:**
```markdown
Verify installation:
```bash
vote-match --version
vote-match --help
```
```

---

## Usage Documentation

### CLI-Specific Documentation Standards

**Command Syntax:**
```markdown
### Command: `mycli subcommand`

**Syntax:**
```bash
mycli subcommand [OPTIONS] <required-arg> [optional-arg]
```

**Arguments:**
- `<required-arg>`: Description of required argument
- `[optional-arg]`: Description of optional argument

**Options:**
- `-h, --help`: Show help message
- `-v, --verbose`: Increase verbosity
- `-o, --output FILE`: Output file path
- `--flag`: Boolean flag

**Exit Codes:**
- `0`: Success
- `1`: General error
- `2`: Invalid usage
```

**Flag Documentation Standards:**
```markdown
### Common Flags

- `-h, --help`: Display help and exit
- `-V, --version`: Display version and exit
- `-v, --verbose`: Increase output verbosity
- `-q, --quiet`: Suppress non-error output
- `--no-color`: Disable colored output
- `-o, --output FILE`: Specify output file
- `-n, --dry-run`: Show what would be done
```

---

## Examples and Code Samples

### Example Best Practices

**1. Progressive Complexity:**
```markdown
## Examples

### Basic Usage
```bash
mycli process file.txt
```

### Intermediate Usage
```bash
mycli process file.txt --output result.txt --verbose
```

### Advanced Usage
```bash
mycli process input.txt \
  --filter "type:important" \
  --transform uppercase \
  --output result.txt
```
```

**2. Show Expected Output:**
```markdown
### Example: Status Check

```bash
$ vote-match status
```

Output:
```
Voter Records:     10,000
Geocoded:          9,500 (95%)
Not Geocoded:        500 (5%)
```
```

**3. Real-World Scenarios:**
```markdown
### Common Workflows

**Scenario 1: Initial Data Import**
```bash
vote-match init-db
vote-match load-csv data.csv
vote-match geocode --service census
```

**Scenario 2: Update Existing Data**
```bash
vote-match load-csv updates.csv
vote-match geocode --service census --reprocess
```
```

---

## Configuration and Environment

### XDG Base Directory Specification

Follow the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html):

```markdown
## File Locations

### Configuration Files
- Linux/macOS: `~/.config/vote-match/config.yaml`
- Windows: `%LOCALAPPDATA%\vote-match\config.yaml`

### Data Files
- Linux/macOS: `~/.local/share/vote-match/`
- Windows: `%LOCALAPPDATA%\vote-match\data\`

### Cache Files
- Linux: `~/.cache/vote-match/`
- macOS: `~/Library/Caches/vote-match/`
- Windows: `%LOCALAPPDATA%\vote-match\cache\`
```

### Environment Variables

**Document all environment variables:**
```markdown
## Environment Variables

### Required
- `DATABASE_URL`: PostgreSQL connection string
  - Format: `postgresql://user:password@host:port/database`

### Optional
- `LOG_LEVEL`: Logging verbosity (default: INFO)
  - Values: DEBUG, INFO, WARNING, ERROR
- `NO_COLOR`: Disable colored output
- `VOTE_MATCH_CONFIG`: Override default config file location
```

---

## CLI-Specific Best Practices

### Input/Output Documentation

```markdown
## Input/Output

### Standard Streams

**stdin**: Accepts input from pipes
```bash
cat voters.csv | vote-match import -
```

**stdout**: Outputs results
```bash
vote-match export --format json > voters.json
```

**stderr**: Displays progress and errors
```bash
vote-match geocode 2> errors.log
```

### Output Formats
```bash
# Human-readable
vote-match list

# JSON for scripting
vote-match list --json

# CSV for spreadsheets
vote-match export --format csv
```
```

### Exit Codes

```markdown
## Exit Codes

- `0`: Successful execution
- `1`: General error
- `2`: Invalid command-line usage
- `3`: Database connection error
- `4`: Geocoding service error
- `130`: Interrupted by user (Ctrl+C)
```

---

## Accessibility Considerations

### Color Output

```markdown
## Accessibility

### Colored Output

Colors are automatically disabled when:
- Output is redirected to a file or pipe
- `NO_COLOR` environment variable is set
- `--no-color` flag is passed
- Terminal doesn't support colors

**Disable colors:**
```bash
export NO_COLOR=1
vote-match status

# or
vote-match status --no-color
```

### Verbose and Quiet Modes

```bash
# Quiet mode (only errors)
vote-match geocode --quiet

# Verbose mode
vote-match geocode --verbose

# Debug mode
vote-match geocode -vv
```
```

---

## Visual Elements

### Badges

```markdown
# vote-match

[![PyPI version](https://badge.fury.io/py/vote-match.svg)](https://pypi.org/project/vote-match/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/user/vote-match/workflows/CI/badge.svg)](https://github.com/user/vote-match/actions)
```

### Screenshots and Demos

```markdown
## Screenshots

### Basic Usage
![Basic usage example](docs/images/basic-usage.png)

### Status Dashboard
```
╭─────────────── Vote Match Status ───────────────╮
│ Database: Connected ✓                           │
│ Records:  10,000                                │
│ Geocoded: 9,500 (95%)                           │
╰─────────────────────────────────────────────────╯
```
```

---

## Maintenance and Updates

### Versioning

```markdown
## Version History

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

### Current Version: 1.2.0

**What's New:**
- Added Nominatim geocoding service
- Improved performance by 40%
- Bug fixes

### Upgrading

```bash
uv add vote-match@latest
vote-match db-upgrade
```
```

---

## Checklist

### Essential Elements
- [ ] Clear, descriptive title
- [ ] One-line description
- [ ] Installation instructions
- [ ] Quick start guide
- [ ] Basic usage examples
- [ ] License information

### CLI-Specific
- [ ] All commands documented
- [ ] Required vs. optional arguments marked
- [ ] Common flags listed
- [ ] Exit codes documented
- [ ] Environment variables documented
- [ ] Configuration file format
- [ ] Input/output formats explained

### User Experience
- [ ] Table of contents
- [ ] Progressive examples
- [ ] Expected output shown
- [ ] Troubleshooting section

### Accessibility
- [ ] NO_COLOR support documented
- [ ] Verbose/quiet mode options
- [ ] Works in non-TTY environments

### Community
- [ ] Contributing guidelines
- [ ] Link to issue tracker
- [ ] Credits and acknowledgments

---

## Summary

A great CLI README:
- **Starts with a clear description** of what the tool does
- **Provides multiple installation methods** that work
- **Shows examples before explaining** (show, don't just tell)
- **Documents all commands, flags, and options** comprehensively
- **Respects user preferences** (colors, verbosity, configuration)
- **Explains exit codes and error handling** for scripting
- **Follows standards** (XDG, NO_COLOR, semantic versioning)
- **Stays current** with the actual tool behavior

Remember: Your README is your CLI's interface for humans. Make it as polished and user-friendly as the CLI itself.

---

## Further Reading

**CLI Design:**
- [clig.dev](https://clig.dev/) - Command Line Interface Guidelines
- [12 Factor CLI Apps](https://medium.com/@jdxcode/12-factor-cli-apps-dd3c227a0e46)

**README Best Practices:**
- [Make a README](https://www.makeareadme.com/)
- [Awesome README](https://github.com/matiassingers/awesome-readme)

**Accessibility:**
- [NO_COLOR standard](https://no-color.org/)
