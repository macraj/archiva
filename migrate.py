#!/usr/bin/env python3
"""
Skrypt migracji bazy danych - dodaje nowe tabele i kolumny
BEZPIECZNIE - tworzy kopię zapasową przed zmianami
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

# Ładuj zmienne środowiskowe z .env jeśli istnieje
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    print(f"Ładowanie zmiennych z: {env_path}")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

# Ustaw domyślne zmienne środowiskowe jeśli nie istnieją
os.environ.setdefault('ARCHIVA_CRED_KEY', 'dev-change-me-32-chars-key-here!!')
os.environ.setdefault('ARCHIVA_DATA_DIR', '/mnt/data/archiva')
os.environ.setdefault('ARCHIVA_DB_PATH', '/mnt/data/archiva/db/app.db')
os.environ.setdefault('ARCHIVA_SESSION_SECRET', 'dev-change-me-session-secret')

# Dodaj ścieżkę do projektu
sys.path.insert(0, str(Path(__file__).parent))

# Teraz importuj moduły app
from app.db import engine
from app.config import DB_PATH
from app.models import Base

def backup_database():
    """Tworzy kopię zapasową bazy danych"""
    db_path = Path(DB_PATH)
    
    # Upewnij się, że katalog istnieje
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    if db_path.exists():
        backup_path = db_path.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        print(f"Tworzę kopię zapasową: {backup_path}")
        shutil.copy2(db_path, backup_path)
        return backup_path
    else:
        print(f"Baza danych nie istnieje: {db_path}")
        print("Tworzę nową bazę danych...")
        return None

def check_existing_tables():
    """Sprawdza istniejące tabele"""
    db_path = Path(DB_PATH)
    
    if not db_path.exists():
        print("Baza danych nie istnieje - zostanie utworzona od zera")
        return []
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        print("Istniejące tabele:", tables)
        return tables

def migrate_with_sqlalchemy():
    """Migracja przy użyciu SQLAlchemy (tylko dodaje brakujące tabele)"""
    print("Migracja z SQLAlchemy...")
    
    # Upewnij się, że katalog bazy danych istnieje
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # To NIE USUWA istniejących danych!
    # Tylko tworzy brakujące tabele
    Base.metadata.create_all(bind=engine)
    print("✓ SQLAlchemy migration applied")

def migrate_manual():
    """Ręczna migracja - dodaje brakujące kolumny do istniejących tabel"""
    print("Sprawdzam potrzebne zmiany...")
    
    db_path = Path(DB_PATH)
    if not db_path.exists():
        print("Baza danych nie istnieje - pomijam ręczną migrację")
        return
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Sprawdź czy tabela mail_accounts istnieje
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mail_accounts';")
        if not cursor.fetchone():
            print("Tabela mail_accounts nie istnieje - pomijam")
            return
        
        # Sprawdź kolumny w mail_accounts
        cursor.execute("PRAGMA table_info(mail_accounts)")
        columns = [col[1] for col in cursor.fetchall()]
        print("Obecne kolumny w mail_accounts:", columns)
        
        # Lista nowych kolumn do dodania
        new_columns = [
            ('last_sync_at', 'DATETIME', 'NULL'),
            ('last_sync_status', 'VARCHAR(50)', 'NULL'),
            ('emails_count', 'INTEGER', '0'),
            ('last_sync_error', 'TEXT', 'NULL')
        ]
        
        for col_name, col_type, default in new_columns:
            if col_name not in columns:
                print(f"  Dodaję kolumnę: {col_name}")
                try:
                    sql = f"ALTER TABLE mail_accounts ADD COLUMN {col_name} {col_type}"
                    if default != 'NULL':
                        sql += f" DEFAULT {default}"
                    cursor.execute(sql)
                    print(f"  ✓ Dodano {col_name}")
                except sqlite3.Error as e:
                    print(f"  ✗ Błąd przy dodawaniu {col_name}: {e}")
        
        conn.commit()
        print("✓ Ręczna migracja zakończona")

def verify_migration():
    """Weryfikuje czy migracja się udała"""
    print("\nWeryfikacja migracji...")
    
    db_path = Path(DB_PATH)
    
    if not db_path.exists():
        print("Baza danych nie została utworzona!")
        return
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Sprawdź tabele
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        print("Tabele po migracji:", tables)
        
        # Sprawdź kolumny w mail_accounts
        if 'mail_accounts' in tables:
            cursor.execute("PRAGMA table_info(mail_accounts)")
            columns = cursor.fetchall()
            print("\nKolumny w mail_accounts:")
            for col in columns:
                print(f"  {col[1]} ({col[2]}) {'NULL' if not col[3] else 'NOT NULL'}")
        
        # Sprawdź kolumny w archived_emails
        if 'archived_emails' in tables:
            cursor.execute("PRAGMA table_info(archived_emails)")
            columns = cursor.fetchall()
            print("\nKolumny w archived_emails:")
            for col in columns:
                print(f"  {col[1]} ({col[2]}) {'NULL' if not col[3] else 'NOT NULL'}")
        
        # Sprawdź liczbę rekordów
        print("\nLiczba rekordów:")
        for table in ['users', 'mail_accounts', 'archived_emails']:
            if table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"  {table}: {count} rekordów")

def create_initial_data():
    """Tworzy przykładowe dane jeśli baza jest pusta"""
    db_path = Path(DB_PATH)
    
    if not db_path.exists():
        print("Baza danych nie istnieje - nie mogę tworzyć danych początkowych")
        return
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Sprawdź czy są jacyś użytkownicy
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        if user_count == 0:
            print("\nBrak użytkowników - tworzę przykładowego admina...")
            # Hasło: admin123 (bcrypt hash)
            admin_hash = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
            cursor.execute("""
                INSERT INTO users (email, password_hash, role, is_active, created_at)
                VALUES (?, ?, 'admin', 1, datetime('now'))
            """, ('admin@example.com', admin_hash))
            conn.commit()
            print("✓ Utworzono admin@example.com (hasło: admin123)")

def main():
    print("=" * 60)
    print("ARCHIVA - MIGRACJA BAZY DANYCH")
    print("=" * 60)
    
    print(f"Ścieżka bazy danych: {DB_PATH}")
    print(f"Katalog danych: {Path(DB_PATH).parent}")
    
    # Krok 1: Kopia zapasowa
    backup_file = backup_database()
    if backup_file:
        print(f"Kopia zapasowa zapisana jako: {backup_file.name}")
    
    # Krok 2: Sprawdź obecny stan
    existing_tables = check_existing_tables()
    
    # Krok 3: Migracja ręczna (dodaje kolumny do istniejących tabel)
    migrate_manual()
    
    # Krok 4: Utwórz wszystkie tabele (SQLAlchemy)
    migrate_with_sqlalchemy()
    
    # Krok 5: Utwórz dane początkowe jeśli potrzebne
    create_initial_data()
    
    # Krok 6: Weryfikacja
    verify_migration()
    
    print("\n" + "=" * 60)
    print("MIGRACJA ZAKOŃCZONA POMYŚLNIE!")
    print("=" * 60)
    
    if backup_file:
        print(f"\n⚠️  Kopia zapasowa: {backup_file}")
        print("   Możesz ją usunąć po potwierdzeniu, że wszystko działa.")
    
    print("\nNastępne kroki:")
    print("1. Uruchom aplikację: ./run-dev.sh")
    print("2. Przejdź do: http://localhost:8000")
    print("3. Jeśli to pierwsze uruchomienie, użyj /setup")
    print("4. Sprawdź archiwum maili: /emails")

if __name__ == "__main__":
    main()