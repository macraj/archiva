# Archiva Web Application

Python web application running on Alpine Linux.

## Setup

1. Clone the repository
2. Create virtual environment: `python -m venv .venv`
3. Activate: `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and configure
6. Run: `./run-dev.sh`

## Project Structure

- `app/` - Main application code
- `requirements.txt` - Python dependencies
- `run-dev.sh` - Development server script
- `install.sh` - Installation script

## Requirements

- Python 3.8+
- See `requirements.txt` for dependencies
