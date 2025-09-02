import sqlite3
import pandas as pd
import hashlib
from db import get_conn
from datetime import datetime

def create_user(email, name, role, password, manager_id, division,
                join_date=None, probation_date=None, permanent_date=None, sick_balance=6):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    from auth import hash_pw
    cur.execute("""INSERT INTO users(email,name,role,manager_id,password_hash,created_at,updated_at,division,join_date,probation_date,permanent_date,sick_balance)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (email, name, role, manager_id, hash_pw(password), now, now, division, join_date, probation_date, permanent_date, sick_balance))
    conn.commit()
    conn.close()

def update_user(user_id, email, name, role, manager_id, new_password, division,
                join_date=None, probation_date=None, permanent_date=None, sick_balance=None):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    from auth import hash_pw
    if new_password:
        cur.execute("""UPDATE users SET email=?, name=?, role=?, manager_id=?, password_hash=?, division=?, join_date=?, probation_date=?, permanent_date=?, sick_balance=?, updated_at=?
                       WHERE id=?""",
                    (email, name, role, manager_id, hash_pw(new_password), division, join_date, probation_date, permanent_date, sick_balance, now, user_id))
    else:
        cur.execute("""UPDATE users SET email=?, name=?, role=?, manager_id=?, division=?, join_date=?, probation_date=?, permanent_date=?, sick_balance=?, updated_at=?
                       WHERE id=?""",
                    (email, name, role, manager_id, division, join_date, probation_date, permanent_date, sick_balance, now, user_id))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM requests WHERE user_id=? LIMIT 1", (user_id,))
    if cur.fetchone():
        conn.close()
        raise ValueError("Tidak bisa hapus user: masih ada request sebagai pemilik. Hapus/arsipkan dulu request-nya.")
    cur.execute("SELECT 1 FROM quotas WHERE user_id=? LIMIT 1", (user_id,))
    if cur.fetchone():
        conn.close()
        raise ValueError("Tidak bisa hapus user: masih ada kuota terkait. Hapus kuotanya dulu.")
    cur.execute("UPDATE users SET manager_id=NULL WHERE manager_id=?", (user_id,))
    cur.execute("UPDATE requests SET manager_by=NULL WHERE manager_by=?", (user_id,))
    cur.execute("UPDATE requests SET hr_by=NULL WHERE hr_by=?", (user_id,))
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

def list_users():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT u.id, u.email, u.name, u.role, u.manager_id, u.division, u.join_date, u.probation_date, u.permanent_date, u.sick_balance, 
	       m.name as manager_name, u.created_at
        FROM users u LEFT JOIN users m ON m.id = u.manager_id
        ORDER BY u.created_at DESC
    """, conn)
    conn.close()
    return df

def list_managers():
    conn = get_conn()
    df = pd.read_sql_query("SELECT id, name, email FROM users WHERE role='MANAGER' ORDER by name", conn)
    conn.close()
    return df

def upsert_quota(user_id, year, leave_total, changeoff_earned, changeoff_used, leave_used):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM quotas WHERE user_id=? AND year=?", (user_id, year))
    row = cur.fetchone()
    if row:
        cur.execute("""UPDATE quotas SET leave_total=?, leave_used=?, changeoff_earned=?, changeoff_used=?, updated_at=?
                       WHERE user_id=? AND year=?""",
                    (leave_total, leave_used, changeoff_earned, changeoff_used, now, user_id, year))
    else:
        cur.execute("""INSERT INTO quotas(user_id,year,leave_total,leave_used,changeoff_earned,changeoff_used,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (user_id, year, leave_total, leave_used, changeoff_earned, changeoff_used, now, now))
    conn.commit()
    conn.close()

def delete_quota(user_id, year):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM quotas WHERE user_id=? AND year=?", (user_id, year))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row
