# SET_PAGE_CONFIG HARUS DI PALING ATAS SEBELUM IMPORT LAINNYA
import streamlit as st
st.set_page_config(page_title="HR-MS CISTECH", layout="wide")

# IMPORT LAINNYA SETELAH SET_PAGE_CONFIG
from business import get_db_connection
from auth import login
from ui_employee import (
    page_employee_dashboard, page_submit_leave,
    page_submit_changeoff, page_my_requests
)
from ui_manager import (
    page_manager_pending, page_manager_team
)
from ui_hr import (
    page_hr_pending, page_hr_quotas, page_hr_users
)
from business import current_year
from business import auto_increment_leave_balance
auto_increment_leave_balance()
import os

# TAMBAHKAN IMPORT init_db DARI db.py
from db import init_db

def sidebar_menu():
    user = st.session_state.user
    if not user:
        return None
    with st.sidebar:
        st.write(f"Logged in as: {user['name']} ({user['role']})")
        if user.get("division"):
            st.caption(f"Division: {user['division']}")
        choice = None
        if user["role"] == "EMPLOYEE":
            choice = st.radio("Menu", ["Dashboard", "Submit Leave", "Submit Change Off", "My Requests"])
        elif user["role"] == "MANAGER":
            choice = st.radio("Menu", ["Dashboard", "Submit Leave", "Submit Change Off", "Pending (Manager)", "Team Requests"])
        elif user["role"] == "HR_ADMIN":
            choice = st.radio("Menu", ["Pending (HR)", "Quotas", "Users"])
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()
        return choice

def page_login():
    st.title("HRMS - Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = login(email, password)
        if user:
            st.session_state.user = dict(user)
            st.session_state.authenticated = True
            st.success(f"Login sukses. Halo, {user['name']}!")
            st.rerun()
        else:
            st.error("Email atau password salah.")

def init_application():
    """Initialize the application"""
    init_db()  # Initialize database
    # Other initialization code...

def main():
    # Logo
    logo_path = "cistech.png"
    if os.path.exists(logo_path):
        col1, col2 = st.columns([1, 4])
        with col1:
            st.image(logo_path, width=280)
    
    # Initialize application
    init_application()
    
    if not st.session_state.get("authenticated", False):
        page_login()
        return
    
    user = st.session_state.user
    if not user:
        page_login()
        return
    
    choice = sidebar_menu()
    
    if user["role"] == "EMPLOYEE":
        if choice == "Dashboard":
            page_employee_dashboard(user)
        elif choice == "Submit Leave":
            page_submit_leave(user)
        elif choice == "Submit Change Off":
            page_submit_changeoff(user)
        elif choice == "My Requests":
            page_my_requests(user)
    
    elif user["role"] == "MANAGER":
        if choice == "Dashboard":
            page_employee_dashboard(user)
        elif choice == "Submit Leave":
            page_submit_leave(user)
        elif choice == "Submit Change Off":
            page_submit_changeoff(user)
        elif choice == "Pending (Manager)":
            page_manager_pending(user)
        elif choice == "Team Requests":
            page_manager_team(user)
    
    elif user["role"] == "HR_ADMIN":
        if choice == "Pending (HR)":
            page_hr_pending(user)
        elif choice == "Quotas":
            page_hr_quotas(user)
        elif choice == "Users":
            page_hr_users(user)

if __name__ == "__main__":
    main()
