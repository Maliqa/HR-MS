import json
import pandas as pd
import pytz
from datetime import datetime, date, timedelta
from db import get_conn
from models import *
import streamlit as st
import hashlib

# Tambahkan fungsi koneksi database
def get_db_connection():
    """Membuat koneksi ke database SQLite"""
    conn = sqlite3.connect('database.db')  # Ganti dengan path database kamu
    conn.row_factory = sqlite3.Row
    return conn

# Fungsi reset kuota yang diperbaiki
def hr_reset_quotas_incremental(year):
    """
    Reset semua kuota dengan logika sederhana:
    - Setiap user dapat +1 saldo cuti
    """
    try:
        conn = get_db_connection()
        
        # Hitung berapa user yang diupdate
        updated_count = 0
        
        # Dapatkan semua user
        users_df = list_users()
        
        for _, user in users_df.iterrows():
            user_id = int(user["id"])
            current_quota = user_quota(user_id, year)
            current_total = int(current_quota["leave_total"])
            
            # Tambah 1 saldo untuk semua user
            new_leave_total = current_total + 1
            updated_count += 1
            
            # Update kuota
            upsert_quota(
                user_id, year, 
                new_leave_total,
                int(current_quota["co_earned"]),
                int(current_quota["co_used"]),
                int(current_quota["leave_used"])
            )
        
        conn.close()
        
        return {
            "updated_count": updated_count,
            "total_users": len(users_df)
        }
        
    except Exception as e:
        print(f"Error in hr_reset_quotas_incremental: {e}")
        raise e

def get_user_related_data(user_id):
    """
    Cek data terkait user sebelum menghapus
    """
    try:
        conn = get_db_connection()
        related_data = {}
        
        # Cek quotas
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM quotas WHERE user_id = ?", (user_id,))
        related_data['quotas'] = cursor.fetchone()[0]
        
        # Cek leave_requests
        cursor.execute("SELECT COUNT(*) FROM leave_requests WHERE user_id = ?", (user_id,))
        related_data['leave_requests'] = cursor.fetchone()[0]
        
        # Cek changeoff_requests
        cursor.execute("SELECT COUNT(*) FROM changeoff_requests WHERE user_id = ?", (user_id,))
        related_data['changeoff_requests'] = cursor.fetchone()[0]
        
        conn.close()
        return related_data
        
    except Exception as e:
        print(f"Error checking related data: {e}")
        return {}

def delete_user_safe(user_id):
    """
    Hapus user dengan aman setelah cek data terkait
    """
    try:
        # Cek data terkait
        related_data = get_user_related_data(user_id)
        
        # Jika ada data terkait, return False
        if any(count > 0 for count in related_data.values()):
            return False
        
        # Hapus user
        return delete_user(user_id)
        
    except Exception as e:
        print(f"Error in safe delete: {e}")
        return False

def soft_delete_user(user_id):
    """
    Soft delete - hanya menandai user sebagai non-aktif
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Set status user menjadi inactive
        cursor.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        
        # 2. Set employee yang managed oleh user ini menjadi tanpa manager
        cursor.execute("UPDATE users SET manager_id = NULL WHERE manager_id = ?", (user_id,))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error in soft_delete_user: {e}")
        return False

def list_users(active_only=True):
    """Mendapatkan daftar semua users (hanya yang aktif secara default)"""
    try:
        conn = get_db_connection()
        if active_only:
            query = "SELECT * FROM users WHERE is_active = 1"
        else:
            query = "SELECT * FROM users"
        result = pd.read_sql_query(query, conn)
        conn.close()
        return result
    except Exception as e:
        print(f"Error getting users: {e}")
        return pd.DataFrame()

# Pastikan semua fungsi yang menggunakan database menggunakan get_db_connection()
def list_users():
    """Mendapatkan daftar semua users"""
    try:
        conn = get_db_connection()
        query = "SELECT * FROM users"
        result = pd.read_sql_query(query, conn)
        conn.close()
        return result
    except Exception as e:
        print(f"Error getting users: {e}")
        return pd.DataFrame()

def user_quota(user_id, year):
    """Mendapatkan kuota user"""
    try:
        conn = get_db_connection()
        query = "SELECT * FROM quotas WHERE user_id = ? AND year = ?"
        result = pd.read_sql_query(query, conn, params=(user_id, year))
        conn.close()
        
        if result.empty:
            # Return default quota jika tidak ada data
            return {
                "leave_total": 0,
                "leave_used": 0,
                "co_earned": 0,
                "co_used": 0
            }
        
        return result.iloc[0].to_dict()
    except Exception as e:
        print(f"Error getting user quota: {e}")
        return {
            "leave_total": 0,
            "leave_used": 0,
            "co_earned": 0,
            "co_used": 0
        }

def upsert_quota(user_id, year, leave_total, co_earned, co_used, leave_used):
    """Insert atau update kuota user"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Cek apakah kuota sudah ada
        check_query = "SELECT COUNT(*) FROM quotas WHERE user_id = ? AND year = ?"
        cursor.execute(check_query, (user_id, year))
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            # Update existing quota
            update_query = """
                UPDATE quotas 
                SET leave_total = ?, leave_used = ?, co_earned = ?, co_used = ?
                WHERE user_id = ? AND year = ?
            """
            cursor.execute(update_query, (leave_total, leave_used, co_earned, co_used, user_id, year))
        else:
            # Insert new quota
            insert_query = """
                INSERT INTO quotas (user_id, year, leave_total, leave_used, co_earned, co_used)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            cursor.execute(insert_query, (user_id, year, leave_total, leave_used, co_earned, co_used))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error upserting quota: {e}")
        return False


def parse_date(date_string):
    """Parse date string dengan berbagai format yang flexible"""
    if not date_string:
        return None
        
    try:
        # Coba parse dengan pandas yang lebih flexible
        return pd.to_datetime(date_string).date()
    except Exception as e:
        try:
            # Fallback: handle berbagai format
            if 'T' in date_string:
                # Format ISO dengan timezone
                if 'Z' in date_string:
                    return datetime.fromisoformat(date_string.replace('Z', '+00:00')).date()
                else:
                    return datetime.fromisoformat(date_string).date()
            else:
                # Format simple YYYY-MM-DD
                return datetime.strptime(date_string, '%Y-%m-%d').date()
        except:
            st.warning(f"Tidak bisa parse date: {date_string}")
            return None

def current_year() -> int:
    return date.today().year

def get_current_time():
    """Mendapatkan waktu sekarang dengan timezone Asia/Jakarta"""
    return datetime.now(pytz.timezone('Asia/Jakarta'))

def get_manager_for_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.*
        FROM users u
        LEFT JOIN users m ON m.id = u.manager_id
        WHERE u.id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def require_manager_assigned(user):
    mgr = get_manager_for_user(int(user["id"]))
    if not mgr:
        st.error("Akun Anda belum memiliki Manager yang ditetapkan. Hubungi HR untuk mengatur Manager terlebih dahlu.")
        return False
    if mgr["role"] != "MANAGER":
        st.error(f"Manager yang ditetapkan adalah {mgr['name']} ({mgr['email']}) tetapi rolenya {mgr['role']}. HR perlu memperbaiki.")
        return False
    return True

def inclusive_days(d1: date, d2: date):
    return (d2 - d1).days + 1

def hr_reset_quotas(year, leave_total=12, co_earned=0):
    """HR function to reset all quotas for a year"""
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    cur.execute("""
        UPDATE quotas 
        SET leave_total = ?, leave_used = 0, 
            changeoff_earned = ?, changeoff_used = 0,
            updated_at = ?
        WHERE year = ?
    """, (leave_total, co_earned, now, year))
    
    conn.commit()
    conn.close()
    return True
def get_or_create_quota(user_id, year):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM quotas WHERE user_id=? AND year=?", (user_id, year))
    q = cur.fetchone()
    if not q:
        now = get_current_time().isoformat()
        cur.execute("""INSERT INTO quotas(user_id,year,leave_total,leave_used,changeoff_earned,changeoff_used,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (user_id, year, 12, 0, 0, 0, now, now))
        conn.commit()
        cur.execute("SELECT * FROM quotas WHERE user_id=? AND year=?", (user_id, year))
        q = cur.fetchone()
    conn.close()
    return q

def user_quota(user_id, year):
    q = get_or_create_quota(user_id, year)
    return {
        "year": year,
        "leave_total": int(q["leave_total"]),
        "leave_used": int(q["leave_used"]),
        "leave_balance": int(q["leave_total"] - q["leave_used"]),
        "co_earned": int(q["changeoff_earned"]),
        "co_used": int(q["changeoff_used"]),
        "co_balance": int(q["changeoff_earned"] - q["changeoff_used"]),
    }


def submit_leave(user_id, start, end, reason):
    days = inclusive_days(start, end)
    year = start.year
    q = get_or_create_quota(user_id, year)
    
    leave_balance = q["leave_total"] - q["leave_used"]
    co_balance = q["changeoff_earned"] - q["changeoff_used"]
    
    # VALIDATION FIXED - CEK SALDO CHANGE OFF JIKA REASON = CHANGEOFF
    if reason == 'CHANGEOFF':
        if co_balance <= 0:  # TIDAK PUNYA SALDO SAMA SEKALI
            return False, f"❌ Tidak bisa submit Change Off. Saldo Change Off Anda: {co_balance} hari."
        if co_balance < days:
            return False, f"❌ Saldo Change Off tidak cukup. Tersedia {co_balance} hari, diminta {days}."
    elif reason == 'PERSONAL':
        if leave_balance <= 0:  # TIDAK PUNYA SALDO CUTI
            return False, f"❌ Tidak bisa submit Cuti Personal. Saldo cuti Anda: {leave_balance} hari."
        if leave_balance < days:
            return False, f"❌ Saldo cuti tidak cukup. Tersedia {leave_balance} hari, diminta {days}."
    
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO requests(user_id,type,start_date,end_date,reason,status,created_at,updated_at,file_uploaded)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (user_id, 'LEAVE', start.isoformat(), end.isoformat(), reason, 'PENDING_MANAGER', now, now, 0))
    
    conn.commit()
    conn.close()
    return True, "✅ Leave request terkirim dan menunggu persetujuan Manager."

def submit_sick_leave(user_id, start_date, end_date, has_doctor_note=False, keterangan=""):
    """
    Submit sakit leave - jika tanpa surat dokter, potong saldo sakit
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Hitung hari sakit
        start_dt = parse_date(start_date)
        end_dt = parse_date(end_date)
        days = (end_dt - start_dt).days + 1
        
        now = datetime.now().isoformat()
        status = "PENDING_MANAGER"
        
        if has_doctor_note:
            # Dengan surat dokter - tidak potong saldo sakit
            reason = "SICK_WITH_NOTE"
        else:
            # Tanpa surat dokter - cek saldo sakit
            cursor.execute("SELECT sick_balance FROM users WHERE id = ?", (user_id,))
            sick_balance = cursor.fetchone()["sick_balance"]
            
            if sick_balance < days:
                return False, f"❌ Saldo sakit tidak cukup. Tersedia {sick_balance} hari, butuh {days} hari."
            
            reason = "SICK_WITHOUT_NOTE"
        
        # Insert ke leave_requests
        cursor.execute("""
            INSERT INTO leave_requests 
            (user_id, type, start_date, end_date, reason, keterangan, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, 'LEAVE', start_date, end_date, reason, keterangan, status, now, now))
        
        # Jika tanpa surat dokter, kurangi saldo sakit
        if not has_doctor_note:
            cursor.execute("""
                UPDATE users 
                SET sick_balance = sick_balance - ?, updated_at = ?
                WHERE id = ?
            """, (days, now, user_id))
        
        conn.commit()
        conn.close()
        
        if has_doctor_note:
            return True, "✅ Sakit dengan surat dokter diajukan. Menunggu approval."
        else:
            return True, f"✅ Sakit tanpa surat dokter diajukan. Saldo sakit berkurang {days} hari."
            
    except Exception as e:
        print(f"Error submitting sick leave: {e}")
        return False, "❌ Error mengajukan sakit."

# ... existing code ...

def manager_pending(manager_id):
    """Get pending requests for manager - UPDATED VERSION"""
    try:
        conn = get_conn()
        df = pd.read_sql_query("""
            SELECT 
                r.*,
                u.name as employee_name,
                u.email as employee_email,
                u.division as employee_division
            FROM requests r
            JOIN users u ON u.id = r.user_id
            WHERE r.status = 'PENDING_MANAGER' AND u.manager_id = ?
            ORDER BY r.created_at DESC
        """, conn, params=(manager_id,))
        conn.close()
        return df
    except Exception as e:
        print(f"Error getting manager pending requests: {e}")
        return pd.DataFrame()

def set_manager_decision(manager_id, request_id, approve):
    """Set manager decision - UPDATED VERSION"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Verify manager has authority over this request
        cursor.execute("""
            SELECT r.*, u.manager_id 
            FROM requests r 
            JOIN users u ON u.id = r.user_id 
            WHERE r.id = ?
        """, (request_id,))
        
        request = cursor.fetchone()
        if not request:
            raise Exception("Request tidak ditemukan")
        
        if request["manager_id"] != manager_id:
            raise Exception("Anda tidak memiliki wewenang untuk request ini")
        
        # Update status
        new_status = 'PENDING_HR' if approve else 'REJECTED'
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE requests 
            SET status = ?, manager_at = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, now, now, request_id))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        raise Exception(f"Error setting manager decision: {e}")


def hr_pending():
    """Get pending requests for HR - UPDATED VERSION"""
    try:
        conn = get_conn()
        df = pd.read_sql_query("""
            SELECT 
                r.*,
                u.name as employee_name,
                u.email as employee_email,
                u.division as employee_division,
                u.sick_balance
            FROM requests r
            JOIN users u ON u.id = r.user_id
            WHERE r.status = 'PENDING_HR'
            ORDER BY r.created_at DESC
        """, conn)
        conn.close()
        return df
    except Exception as e:
        print(f"Error getting HR pending requests: {e}")
        return pd.DataFrame()

def set_hr_decision(hr_id, request_id, approve, request_type=None):
    """Set HR decision - UPDATED VERSION"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Get request details
        cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
        request = cursor.fetchone()
        if not request:
            raise Exception("Request tidak ditemukan")
        
        # Update status
        new_status = 'APPROVED' if approve else 'REJECTED'
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE requests 
            SET status = ?, hr_id = ?, hr_at = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, hr_id, now, now, request_id))
        
        # Update quotas if approved
        if approve:
            user_id = request["user_id"]
            year = datetime.fromisoformat(request["created_at"]).year
            
            if request["type"] == "LEAVE" and request["reason"] == "PERSONAL":
                # Deduct leave balance for personal leave
                start_date = datetime.fromisoformat(request["start_date"]).date()
                end_date = datetime.fromisoformat(request["end_date"]).date()
                days = (end_date - start_date).days + 1
                
                # Get current quota
                cursor.execute("SELECT * FROM quotas WHERE user_id = ? AND year = ?", (user_id, year))
                quota = cursor.fetchone()
                
                if quota:
                    new_used = quota["leave_used"] + days
                    cursor.execute("""
                        UPDATE quotas 
                        SET leave_used = ?, updated_at = ?
                        WHERE user_id = ? AND year = ?
                    """, (new_used, now, user_id, year))
                
            elif request["type"] == "CHANGEOFF":
                # Add changeoff balance
                hours = request.get("hours", 0)
                days_earned = int(hours / 8)  # Convert hours to days
                
                cursor.execute("SELECT * FROM quotas WHERE user_id = ? AND year = ?", (user_id, year))
                quota = cursor.fetchone()
                
                if quota:
                    new_earned = quota["changeoff_earned"] + days_earned
                    cursor.execute("""
                        UPDATE quotas 
                        SET changeoff_earned = ?, updated_at = ?
                        WHERE user_id = ? AND year = ?
                    """, (new_earned, now, user_id, year))
                else:
                    # Create new quota if doesn't exist
                    cursor.execute("""
                        INSERT INTO quotas (user_id, year, leave_total, leave_used, changeoff_earned, changeoff_used, created_at, updated_at)
                        VALUES (?, ?, 12, 0, ?, 0, ?, ?)
                    """, (user_id, year, days_earned, now, now))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        raise Exception(f"Error setting HR decision: {e}")

def hr_reset_quotas(year, leave_total=0, co_earned=0):
    """HR function to reset all quotas for a year - TOTAL DI-SET 0"""
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    # RESET SEMUA SALDO KE NOL (TOTAL DAN USED)
    cur.execute("""
        UPDATE quotas 
        SET leave_total = ?, leave_used = 0, 
            changeoff_earned = ?, changeoff_used = 0,
            updated_at = ?
        WHERE year = ?
    """, (leave_total, co_earned, now, year))
    
    conn.commit()
    conn.close()
    return True

def manual_increment_leave_balance(year=None):
    """Manual increment leave balance untuk semua user - PASTI BERJALAN"""
    from db import get_conn
    from datetime import datetime
    
    if year is None:
        year = datetime.now().year
    
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    try:
        # INCREMENT SEMUA USER UNTUK TAHUN INI
        cur.execute("""
            UPDATE quotas 
            SET leave_total = leave_total + 1, updated_at = ?
            WHERE year = ?
        """, (now, year))
        
        # Untuk user yang belum punya quota di tahun ini, buat baru
        cur.execute("""
            INSERT OR IGNORE INTO quotas (user_id, year, leave_total, leave_used, changeoff_earned, changeoff_used, created_at, updated_at)
            SELECT id, ?, 1, 0, 0, 0, ?, ? 
            FROM users 
            WHERE id NOT IN (SELECT user_id FROM quotas WHERE year = ?)
        """, (year, now, now, year))
        
        conn.commit()
        return True, f"✅ Semua user dapat +1 leave balance untuk tahun {year}!"
        
    except Exception as e:
        conn.rollback()
        return False, f"❌ Error: {str(e)}"
    finally:
        conn.close()

def set_manager_decision(manager_id, request_id, approve):
    conn = get_conn()
    cur = conn.cursor()
    
    # Cek apakah request ada dan user memang manager dari employee tersebut
    cur.execute("""SELECT r.*, u.manager_id
                   FROM requests r JOIN users u ON u.id=r.user_id
                   WHERE r.id=?""", (request_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        raise ValueError("Request tidak ditemukan")
    
    # Verifikasi bahwa user memang manager dari employee yang membuat request
    if row['manager_id'] != manager_id:
        conn.close()
        raise ValueError("Anda bukan manager dari employee ini")
    
    # Update status berdasarkan keputusan
    now = datetime.utcnow().isoformat()
    if approve:
        status = 'PENDING_HR'  # Lanjut ke HR
    else:
        status = 'REJECTED'    # Ditolak manager
    
    cur.execute("""
        UPDATE requests 
        SET status = ?, manager_by = ?, manager_at = ?, updated_at = ?
        WHERE id = ?
    """, (status, manager_id, now, now, request_id))
    
    conn.commit()
    conn.close()

def my_requests(user_id: int) -> pd.DataFrame:
    """Get all requests for a user"""
    try:
        conn = get_db_connection()
        
        # Query untuk leave requests
        leave_query = """
            SELECT 
                r.*, 
                'LEAVE' as request_type
            FROM leave_requests r
            WHERE r.user_id = ?
        """
        
        # Query untuk changeoff requests
        changeoff_query = """
            SELECT 
                r.*, 
                'CHANGEOFF' as request_type
            FROM changeoff_requests r
            WHERE r.user_id = ?
        """
        
        # Gabungkan hasil query
        leave_df = pd.read_sql_query(leave_query, conn, params=(user_id,))
        changeoff_df = pd.read_sql_query(changeoff_query, conn, params=(user_id,))
        
        combined_df = pd.concat([leave_df, changeoff_df], ignore_index=True)
        combined_df = combined_df.sort_values('created_at', ascending=False)
        
        conn.close()
        return combined_df
        
    except Exception as e:
        print(f"Error getting user requests: {e}")
        return pd.DataFrame()

# --- FUNGSI USER MANAGEMENT YANG DIPERBAIKI ---

def list_users():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT u.*, m.name as manager_name 
        FROM users u 
        LEFT JOIN users m ON u.manager_id = m.id 
        ORDER BY u.name
    """, conn)
    conn.close()
    return df

def get_sick_balance(user_id):
    """
    Dapatkan saldo sakit user
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sick_balance FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result["sick_balance"] if result else 6
    except Exception as e:
        print(f"Error getting sick balance: {e}")
        return 6


def list_managers():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM users WHERE role='MANAGER' ORDER BY name", conn)
    conn.close()
    return df

def create_user(email, name, role, password, manager_id=None, division=None, 
                join_date=None, probation_date=None, permanent_date=None, 
                sick_balance=6, nik=None):
    """
    Membuat user baru dengan parameter NIK
    """
    conn = get_conn()
    cur = conn.cursor()
    
    # Hash password - PERBAIKAN: gunakan password_hash bukan password
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    
    now = datetime.utcnow().isoformat()
    
    # PERBAIKAN: gunakan password_hash bukan password
    cur.execute("""
        INSERT INTO users (email, name, role, password_hash, manager_id, division, 
                          join_date, probation_date, permanent_date, sick_balance, nik,
                          created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (email, name, role, hashed_password, manager_id, division,
          join_date, probation_date, permanent_date, sick_balance, nik,
          now, now))
    
    conn.commit()
    conn.close()

def update_user(user_id, email, name, role, manager_id=None, password=None, division=None,
                join_date=None, probation_date=None, permanent_date=None, sick_balance=6, nik=None):
    """
    Mengupdate user dengan parameter NIK
    """
    conn = get_conn()
    cur = conn.cursor()
    
    # Jika password direset, hash password baru - PERBAIKAN: gunakan password_hash
    if password:
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        cur.execute("""
            UPDATE users 
            SET email=?, name=?, role=?, password_hash=?, manager_id=?, division=?,
                join_date=?, probation_date=?, permanent_date=?, sick_balance=?, nik=?,
                updated_at=?
            WHERE id=?
        """, (email, name, role, hashed_password, manager_id, division,
              join_date, probation_date, permanent_date, sick_balance, nik,
              datetime.utcnow().isoformat(), user_id))
    else:
        # Jika password tidak direset, jangan update password
        cur.execute("""
            UPDATE users 
            SET email=?, name=?, role=?, manager_id=?, division=?,
                join_date=?, probation_date=?, permanent_date=?, sick_balance=?, nik=?,
                updated_at=?
            WHERE id=?
        """, (email, name, role, manager_id, division,
              join_date, probation_date, permanent_date, sick_balance, nik,
              datetime.utcnow().isoformat(), user_id))
    
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

def upsert_quota(user_id, year, leave_total, co_earned, co_used, leave_used):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    # Cek apakah quota sudah ada
    cur.execute("SELECT * FROM quotas WHERE user_id=? AND year=?", (user_id, year))
    existing = cur.fetchone()
    
    if existing:
        # Update existing quota
        cur.execute("""
            UPDATE quotas 
            SET leave_total=?, leave_used=?, changeoff_earned=?, changeoff_used=?, updated_at=?
            WHERE user_id=? AND year=?
        """, (leave_total, leave_used, co_earned, co_used, now, user_id, year))
    else:
        # Insert new quota
        cur.execute("""
            INSERT INTO quotas (user_id, year, leave_total, leave_used, changeoff_earned, changeoff_used, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, year, leave_total, leave_used, co_earned, co_used, now, now))
    
    conn.commit()
    conn.close()

def delete_quota(user_id, year):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM quotas WHERE user_id=? AND year=?", (user_id, year))
    conn.commit()
    conn.close()


def auto_increment_leave_balance():
    """Auto increment leave balance every 1st of the month"""
    from db import get_conn
    from datetime import datetime, date
    
    today = date.today()
    if today.day == 1:  # Hanya jalan tiap tanggal 1
        conn = get_conn()
        cur = conn.cursor()
        year = today.year
        
        # Cek apakah table system_settings sudah ada
        try:
            cur.execute("SELECT last_increment FROM system_settings WHERE id=1")
            setting = cur.fetchone()
        except:
            # Jika table belum ada, create dulu
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_settings(
                    id INTEGER PRIMARY KEY,
                    last_increment TEXT,
                    updated_at TEXT NOT NULL
                );
            """)
            setting = None
        
        last_increment = None
        if setting and setting["last_increment"]:
            try:
                last_increment = datetime.fromisoformat(setting["last_increment"]).date()
            except:
                last_increment = None
        
        # Jika belum di-increment bulan ini
        if not last_increment or last_increment.month != today.month:
            now = datetime.utcnow().isoformat()
            
            # Increment semua user
            cur.execute("""
                UPDATE quotas 
                SET leave_total = leave_total + 1, updated_at = ?
                WHERE year = ?
            """, (now, year))
            
            # Update last increment date
            cur.execute("""
                INSERT OR REPLACE INTO system_settings (id, last_increment, updated_at)
                VALUES (1, ?, ?)
            """, (now, now))
            
            conn.commit()
            print(f"✅ Auto increment executed on {today}. All users got +1 leave balance.")
        conn.close()

def get_user_quota_summary(year=None):
    """Get summary report of all users' quotas for the year"""
    from db import get_conn
    import pandas as pd
    
    if year is None:
        year = date.today().year
    
    conn = get_conn()
    
    # Query untuk mendapatkan summary per user
    query = """
    SELECT 
        u.id as user_id,
        u.name as user_name,
        u.email as user_email,
        u.division as user_division,
        u.nik as user_nik,
        q.year as year,
        q.leave_total as leave_total,
        q.leave_used as leave_used,
        q.leave_total - q.leave_used as leave_balance,
        q.changeoff_earned as co_earned,
        q.changeoff_used as co_used,
        q.changeoff_earned - q.changeoff_used as co_balance,
        u.sick_balance as sick_balance,
        CASE 
            WHEN q.leave_balance >= 8 THEN 'Excellent'
            WHEN q.leave_balance >= 4 THEN 'Good' 
            WHEN q.leave_balance >= 1 THEN 'Low'
            ELSE 'Critical'
        END as leave_status,
        CASE 
            WHEN q.co_balance >= 5 THEN 'Excellent'
            WHEN q.co_balance >= 3 THEN 'Good'
            WHEN q.co_balance >= 1 THEN 'Low'
            ELSE 'No Balance'
        END as co_status,
        CASE 
            WHEN u.sick_balance >= 4 THEN 'Sufficient'
            WHEN u.sick_balance >= 2 THEN 'Moderate'
            ELSE 'Low'
        END as sick_status
    FROM users u
    LEFT JOIN quotas q ON u.id = q.user_id AND q.year = ?
    ORDER BY u.name
    """
    
    df = pd.read_sql_query(query, conn, params=(year,))
    conn.close()
    
    return df

def get_semester_report(semester=1, year=None):
    """Get detailed report per semester"""
    from db import get_conn
    import pandas as pd
    
    if year is None:
        year = date.today().year
    
    # Tentukan bulan range berdasarkan semester
    if semester == 1:
        month_range = "01-06"  # Jan-Jun
    else:
        month_range = "07-12"  # Jul-Dec
    
    conn = get_conn()
    
    query = """
    SELECT 
        u.id as user_id,
        u.name as user_name,
        u.nik as user_nik,
        u.division as user_division,
        q.year as year,
        'Semester {}' as semester,
        q.leave_total as total_leave,
        q.leave_used as used_leave,
        q.leave_balance as balance_leave,
        q.changeoff_earned as earned_co,
        q.changeoff_used as used_co,
        q.changeoff_balance as balance_co,
        u.sick_balance as sick_balance,
        COUNT(r.id) as total_requests,
        SUM(CASE WHEN r.status = 'APPROVED' THEN 1 ELSE 0 END) as approved_requests,
        SUM(CASE WHEN r.status LIKE 'PENDING%' THEN 1 ELSE 0 END) as pending_requests
    FROM users u
    LEFT JOIN quotas q ON u.id = q.user_id AND q.year = ?
    LEFT JOIN requests r ON u.id = r.user_id 
        AND strftime('%Y', r.created_at) = ?
        AND strftime('%m', r.created_at) BETWEEN ? AND ?
    GROUP BY u.id
    ORDER BY u.name
    """.format(semester)
    
    # Parse month range
    start_month, end_month = month_range.split('-')
    
    df = pd.read_sql_query(query, conn, params=(year, str(year), start_month, end_month))
    conn.close()
    
    return df



def get_employees_by_manager(manager_id):
    """
    Dapatkan semua employee yang dikelola oleh manager tertentu
    """
    try:
        conn = get_db_connection()
        query = "SELECT id, name, email FROM users WHERE manager_id = ?"
        result = pd.read_sql_query(query, conn, params=(manager_id,))
        conn.close()
        return result.to_dict('records')
    except Exception as e:
        print(f"Error getting employees by manager: {e}")
        return []

def reassign_employees_manager(old_manager_id, new_manager_id):
    """
    Pindahkan semua employee dari manager lama ke manager baru
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if new_manager_id is None:
            query = "UPDATE users SET manager_id = NULL WHERE manager_id = ?"
            cursor.execute(query, (old_manager_id,))
        else:
            query = "UPDATE users SET manager_id = ? WHERE manager_id = ?"
            cursor.execute(query, (new_manager_id, old_manager_id))
        
        conn.commit()
        conn.close()
        return cursor.rowcount
    except Exception as e:
        print(f"Error reassigning employees manager: {e}")
        return 0

def delete_user_with_reassign(user_id, new_manager_id=None):
    """
    Hapus user dengan terlebih dahulu memindahkan employee yang dikelola
    """
    try:
        # Pindahkan employee yang dikelola
        reassign_employees_manager(user_id, new_manager_id)
        
        # Hapus user
        return delete_user(user_id)
    except Exception as e:
        print(f"Error deleting user with reassign: {e}")
        return False

def reassign_employees_manager(old_manager_id, new_manager_id):
    """
    Pindahkan semua employee dari manager lama ke manager baru
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if new_manager_id is None:
            query = "UPDATE users SET manager_id = NULL WHERE manager_id = ?"
            cursor.execute(query, (old_manager_id,))
        else:
            query = "UPDATE users SET manager_id = ? WHERE manager_id = ?"
            cursor.execute(query, (new_manager_id, old_manager_id))
        
        conn.commit()
        conn.close()
        return cursor.rowcount
    except Exception as e:
        print(f"Error reassigning employees manager: {e}")
        return 0

def hr_reset_quotas_special(year):
    """
    Reset semua kuota dengan logika khusus:
    - Setiap reset nambah 1 saldo, maksimal sampai 12
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Hitung statistik
        incremented = 0
        maxed_out = 0
        
        # Dapatkan semua user
        users_df = list_users()
        
        for _, user in users_df.iterrows():
            user_id = int(user["id"])
            current_quota = user_quota(user_id, year)
            current_total = int(current_quota["leave_total"])
            
            # Tentukan increment - tambah 1, maksimal 12
            if current_total < 12:
                new_leave_total = current_total + 1
                incremented += 1
            else:
                new_leave_total = 12  # Maksimal
                maxed_out += 1
            
            # Update kuota
            upsert_quota(
                user_id, year, 
                new_leave_total,
                int(current_quota["co_earned"]),
                int(current_quota["co_used"]),
                int(current_quota["leave_used"])
            )
        
        conn.close()
        
        return {
            "incremented": incremented,
            "maxed_out": maxed_out,
            "total_users": len(users_df)
        }
        
    except Exception as e:
        print(f"Error in hr_reset_quotas_special: {e}")
        raise e


def hr_reset_quotas_to_zero(year):
    """
    Reset semua kuota cuti dan change off ke nol
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        updated_count = 0
        
        # Dapatkan semua user
        users_df = list_users()
        
        for _, user in users_df.iterrows():
            user_id = int(user["id"])
            
            # Reset semua nilai ke 0
            upsert_quota(user_id, year, 0, 0, 0, 0)
            updated_count += 1
        
        conn.close()
        return updated_count
        
    except Exception as e:
        print(f"Error in hr_reset_quotas_to_zero: {e}")
        raise e

def hr_reset_quotas_incremental(year):
    """
    Tambah 1 saldo cuti untuk semua user
    """
    try:
        conn = get_db_connection()
        updated_count = 0
        
        users_df = list_users()
        
        for _, user in users_df.iterrows():
            user_id = int(user["id"])
            current_quota = user_quota(user_id, year)
            current_total = int(current_quota["leave_total"])
            
            # Tambah 1 saldo
            new_leave_total = current_total + 1
            updated_count += 1
            
            upsert_quota(
                user_id, year, 
                new_leave_total,
                int(current_quota["co_earned"]),
                int(current_quota["co_used"]),
                int(current_quota["leave_used"])
            )
        
        conn.close()
        return {"updated_count": updated_count, "total_users": len(users_df)}
        
    except Exception as e:
        print(f"Error in hr_reset_quotas_incremental: {e}")
        raise e

# Tambahkan import
from db import delete_user_complete, clean_orphaned_data

# Update atau tambah fungsi ini
def delete_user_force(user_id):
    """Delete user menggunakan fungsi dari db.py"""
    return delete_user_complete(user_id)

def cleanup_database():
    """Clean orphaned data"""
    return clean_orphaned_data()

