import sqlite3
import os
from datetime import datetime

def get_conn():
    """Membuat koneksi ke database SQLite"""
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect('data/database.db')
    conn.row_factory = sqlite3.Row
    # DISABLE foreign key constraints untuk kemudahan delete
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn

def init_db():
    """Inisialisasi database - buat semua tabel jika belum ada"""
    conn = get_conn()
    cursor = conn.cursor()
    
    # ==================== USERS TABLE ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'EMPLOYEE',
            password_hash TEXT NOT NULL,
            manager_id INTEGER,
            division TEXT,
            join_date TEXT,
            probation_date TEXT,
            permanent_date TEXT,
            sick_balance INTEGER DEFAULT 6,
            nik TEXT UNIQUE,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ==================== QUOTAS TABLE ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quotas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            leave_total INTEGER DEFAULT 0,
            leave_used INTEGER DEFAULT 0,
            changeoff_earned INTEGER DEFAULT 0,
            changeoff_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, year)
        )
    ''')
    
    # ==================== UNIFIED REQUESTS TABLE ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT,
            keterangan TEXT,
            departure_date TEXT,
            return_date TEXT,
            hours INTEGER,
            change_off_days INTEGER DEFAULT 0,
            location TEXT,
            pic TEXT,
            activities_json TEXT,
            status TEXT DEFAULT 'PENDING_MANAGER',
            file_uploaded BOOLEAN DEFAULT FALSE,
            timesheet_path TEXT,
            manager_at TEXT,
            hr_id INTEGER,
            hr_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE requests ADD COLUMN change_off_days INTEGER DEFAULT 0')
        print("✅ Added change_off_days column to requests table")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # ==================== LEGACY TABLES (Keep for backward compatibility) ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL DEFAULT 'LEAVE',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            keterangan TEXT,
            status TEXT DEFAULT 'PENDING_MANAGER',
            file_uploaded BOOLEAN DEFAULT FALSE,
            timesheet_path TEXT,
            manager_by INTEGER,
            manager_at TEXT,
            hr_id INTEGER,
            hr_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS changeoff_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL DEFAULT 'CHANGEOFF',
            departure_date TEXT NOT NULL,
            return_date TEXT NOT NULL,
            hours INTEGER NOT NULL,
            location TEXT,
            pic TEXT,
            keterangan TEXT,
            activities_json TEXT,
            status TEXT DEFAULT 'PENDING_MANAGER',
            file_uploaded BOOLEAN DEFAULT FALSE,
            timesheet_path TEXT,
            manager_by INTEGER,
            manager_at TEXT,
            hr_id INTEGER,
            hr_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ==================== APPROVALS TABLE ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            request_type TEXT NOT NULL,
            approver_id INTEGER NOT NULL,
            approval_type TEXT NOT NULL,
            status TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ==================== NOTIFICATIONS TABLE ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ==================== SYSTEM_SETTINGS TABLE ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY,
            last_increment TEXT,
            updated_at TEXT NOT NULL
        )
    ''')
    
    # ==================== MIGRATE DATA ====================
    migrate_legacy_data(cursor)
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")
    
    # Create default admin user jika belum ada
    create_default_admin()

def migrate_legacy_data(cursor):
    """Migrate data dari tabel terpisah ke tabel requests yang unified"""
    try:
        # Migrate leave_requests to requests
        cursor.execute('''
            INSERT OR IGNORE INTO requests 
            (id, user_id, type, start_date, end_date, reason, keterangan, 
             status, file_uploaded, timesheet_path, manager_at, 
             hr_id, hr_at, created_at, updated_at)
            SELECT id, user_id, 'LEAVE', start_date, end_date, reason, keterangan,
                   status, file_uploaded, timesheet_path, manager_at,
                   hr_id, hr_at, created_at, updated_at
            FROM leave_requests
        ''')
        
        # Migrate changeoff_requests to requests
        cursor.execute('''
            INSERT OR IGNORE INTO requests 
            (id, user_id, type, start_date, end_date, keterangan,
             departure_date, return_date, hours, location, pic, activities_json,
             status, file_uploaded, timesheet_path, manager_at,
             hr_id, hr_at, created_at, updated_at)
            SELECT id, user_id, 'CHANGEOFF', departure_date, return_date, keterangan,
                   departure_date, return_date, hours, location, pic, activities_json,
                   status, file_uploaded, timesheet_path, manager_at,
                   hr_id, hr_at, created_at, updated_at
            FROM changeoff_requests
        ''')
        
        print("✅ Legacy data migrated successfully!")
        
    except Exception as e:
        print(f"⚠️  Migration warning: {e}")

def create_default_admin():
    """Buat default admin user jika belum ada"""
    import hashlib
    conn = get_conn()
    cursor = conn.cursor()
    
    # Cek jika sudah ada admin
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'HR_ADMIN'")
    admin_count = cursor.fetchone()[0]
    
    if admin_count == 0:
        # Hash password untuk admin default
        password_hash = hashlib.sha256("admin123".encode()).hexdigest()
        now = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT INTO users (email, name, role, password_hash, division, sick_balance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("admin@company.com", "Admin User", "HR_ADMIN", password_hash, "HR", 6, now, now))
        
        conn.commit()
        print("✅ Default admin user created: admin@company.com / admin123")
    
    conn.close()

def delete_user_complete(user_id):
    """Delete user dan semua data terkait - TANPA FK CONSTRAINTS"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        print(f"🗑️ Deleting user ID: {user_id}")
        
        # 1. Delete from notifications
        cursor.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
        deleted_notifications = cursor.rowcount
        print(f"   ✅ Deleted {deleted_notifications} notifications")
        
        # 2. Delete from quotas
        cursor.execute("DELETE FROM quotas WHERE user_id = ?", (user_id,))
        deleted_quotas = cursor.rowcount
        print(f"   ✅ Deleted {deleted_quotas} quotas")
        
        # 3. Delete from requests
        cursor.execute("DELETE FROM requests WHERE user_id = ?", (user_id,))
        deleted_requests = cursor.rowcount
        print(f"   ✅ Deleted {deleted_requests} requests")
        
        # 4. Delete from approvals
        cursor.execute("DELETE FROM approvals WHERE approver_id = ?", (user_id,))
        deleted_approvals = cursor.rowcount
        print(f"   ✅ Deleted {deleted_approvals} approvals")
        
        # 5. Update HR references in requests (set to NULL)
        cursor.execute("UPDATE requests SET hr_id = NULL WHERE hr_id = ?", (user_id,))
        updated_hr = cursor.rowcount
        print(f"   ✅ Updated {updated_hr} HR references")
        
        # 6. Update manager references (set to NULL)
        cursor.execute("UPDATE users SET manager_id = NULL WHERE manager_id = ?", (user_id,))
        updated_managers = cursor.rowcount
        print(f"   ✅ Updated {updated_managers} manager references")
        
        # 7. Delete from legacy tables
        try:
            cursor.execute("DELETE FROM leave_requests WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM changeoff_requests WHERE user_id = ?", (user_id,))
            print("   ✅ Cleaned legacy tables")
        except:
            pass
        
        # 8. Finally delete the user
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        deleted_user = cursor.rowcount
        print(f"   ✅ Deleted {deleted_user} user")
        
        if deleted_user == 0:
            print("   ❌ User not found")
            conn.close()
            return False
        
        conn.commit()
        conn.close()
        print(f"✅ User ID {user_id} deleted successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error deleting user: {e}")
        return False

def clean_orphaned_data():
    """Bersihkan data yang tidak memiliki referensi user yang valid"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        print("🧹 Cleaning orphaned data...")
        
        # Clean orphaned requests
        cursor.execute("""
            DELETE FROM requests 
            WHERE user_id NOT IN (SELECT id FROM users)
        """)
        cleaned_requests = cursor.rowcount
        
        # Clean orphaned quotas
        cursor.execute("""
            DELETE FROM quotas 
            WHERE user_id NOT IN (SELECT id FROM users)
        """)
        cleaned_quotas = cursor.rowcount
        
        # Clean orphaned notifications
        cursor.execute("""
            DELETE FROM notifications 
            WHERE user_id NOT IN (SELECT id FROM users)
        """)
        cleaned_notifications = cursor.rowcount
        
        # Clean orphaned approvals
        cursor.execute("""
            DELETE FROM approvals 
            WHERE approver_id NOT IN (SELECT id FROM users)
        """)
        cleaned_approvals = cursor.rowcount
        
        # Fix invalid manager references
        cursor.execute("""
            UPDATE users SET manager_id = NULL 
            WHERE manager_id IS NOT NULL 
            AND manager_id NOT IN (SELECT id FROM users WHERE id != users.id)
        """)
        fixed_managers = cursor.rowcount
        
        # Fix invalid HR references
        cursor.execute("""
            UPDATE requests SET hr_id = NULL 
            WHERE hr_id IS NOT NULL 
            AND hr_id NOT IN (SELECT id FROM users)
        """)
        fixed_hr = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        print(f"✅ Cleaned {cleaned_requests} orphaned requests")
        print(f"✅ Cleaned {cleaned_quotas} orphaned quotas")
        print(f"✅ Cleaned {cleaned_notifications} orphaned notifications")
        print(f"✅ Cleaned {cleaned_approvals} orphaned approvals")
        print(f"✅ Fixed {fixed_managers} invalid manager references")
        print(f"✅ Fixed {fixed_hr} invalid HR references")
        
        return True
        
    except Exception as e:
        print(f"❌ Error cleaning data: {e}")
        return False

def check_database():
    """Cek status database dan tables"""
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        # Cek tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print("📊 Database Tables:")
        for table in tables:
            print(f"   - {table['name']}")
        
        # Cek user count
        cursor.execute("SELECT COUNT(*) as count FROM users")
        user_count = cursor.fetchone()['count']
        print(f"   👥 Total Users: {user_count}")
        
        # Cek admin exists
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'HR_ADMIN'")
        admin_count = cursor.fetchone()['count']
        print(f"   👔 HR Admins: {admin_count}")
        
        # Cek requests count
        cursor.execute("SELECT COUNT(*) as count FROM requests")
        requests_count = cursor.fetchone()['count']
        print(f"   📋 Total Requests: {requests_count}")
        
        # Check for orphaned data
        cursor.execute("""
            SELECT COUNT(*) as count FROM requests 
            WHERE user_id NOT IN (SELECT id FROM users)
        """)
        orphaned_requests = cursor.fetchone()['count']
        if orphaned_requests > 0:
            print(f"   ⚠️  Orphaned Requests: {orphaned_requests}")
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM quotas 
            WHERE user_id NOT IN (SELECT id FROM users)
        """)
        orphaned_quotas = cursor.fetchone()['count']
        if orphaned_quotas > 0:
            print(f"   ⚠️  Orphaned Quotas: {orphaned_quotas}")
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
    finally:
        conn.close()

# Auto initialize database ketika module di-import
if __name__ != "__main__":
    try:
        init_db()
        check_database()
    except Exception as e:
        print(f"❌ Error initializing database: {e}")

# Untuk testing standalone
if __name__ == "__main__":
    init_db()
    check_database()
    
    # Clean orphaned data on startup
    clean_orphaned_data()