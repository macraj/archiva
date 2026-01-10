#!/usr/bin/env python3
"""
Skrypt do automatycznej synchronizacji - uruchamiany przez cron
"""
import sys
import logging
from pathlib import Path

# Dodaj ścieżkę do projektu
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.archive import sync_all_enabled_accounts
from app.db import SessionLocal
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting scheduled sync...")
    results = sync_all_enabled_accounts()
    
    # Podsumowanie
    successful = sum(1 for r in results if r.get('success'))
    total_fetched = sum(r.get('fetched', 0) for r in results)
    
    logger.info(f"Sync completed. Success: {successful}/{len(results)}, Emails: {total_fetched}")
    
    # Zapis do pliku logów
    with open("/tmp/archiva_sync.log", "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} - Synced {total_fetched} emails\n")

if __name__ == "__main__":
    main()
    