import streamlit as st
import hashlib
import sqlite3
from db import get_conn

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def login(email: str, password: str):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        conn.close()
        if not row: 
            return None
        if row["password_hash"] != hash_pw(password): 
            return None
        return row
    except sqlite3.OperationalError as e:
        st.error(f"Login error: {e}")
        return None

def login_form():
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.header("HRMS - Login")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            user = login(email, password)
            if user:
                st.success("Login successful!")
                # lanjutkan ke halaman berikutnya sesuai kebutuhan
            else:
                st.error("Email or password is incorrect.")