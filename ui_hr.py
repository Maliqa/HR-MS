import streamlit as st
import pandas as pd
from business import (
    list_users, list_managers, create_user, update_user, delete_user,
    user_quota, upsert_quota, delete_quota, current_year,
    get_employees_by_manager, delete_user_force,
    hr_reset_quotas_incremental, hr_reset_quotas_to_zero
)
from file_utils import preview_file
from ui_employee import quota_kanban
from db import get_conn
import pytz
from datetime import date, datetime, timedelta
import json

# Style CSS Modern
st.markdown("""
<style>
.main-header {
    font-size: 2.5rem !important;
    color: #2563eb;
    border-bottom: 3px solid #2563eb;
    padding-bottom: 0.5rem;
    margin-bottom: 2rem;
    font-weight: 700;
}
.sub-header {
    font-size: 1.8rem !important;
    color: #2563eb;
    margin: 2rem 0 1rem 0;
    font-weight: 600;
}
.metric-card {
    background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    border-left: 4px solid #2563eb;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}
.user-card {
    background: white;
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    border: 1px solid #e2e8f0;
    transition: all 0.3s ease;
}
.user-card:hover {
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15);
    transform: translateY(-2px);
}
.success-banner {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    padding: 1rem;
    border-radius: 8px;
    margin: 1rem 0;
}
.sick-balance-badge {
    background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
    color: white;
    padding: 0.5rem 1rem;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

# ==============================================
# UTILITY FUNCTIONS
# ==============================================

def convert_to_local_time(utc_string, user_timezone='Asia/Jakarta'):
    """Konversi UTC time ke waktu lokal user"""
    if not utc_string:
        return ""
    try:
        utc_time = datetime.fromisoformat(utc_string.replace('Z', '+00:00'))
        user_tz = pytz.timezone(user_timezone)
        local_time = utc_time.astimezone(user_tz)
        return local_time.strftime('%Y-%m-%d %H:%M:%S (%Z)')
    except:
        return utc_string

def format_date_for_display(date_string, user_timezone='Asia/Jakarta'):
    """Format tanggal untuk display dengan timezone"""
    if not date_string:
        return ""
    try:
        date_obj = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        user_tz = pytz.timezone(user_timezone)
        local_date = date_obj.astimezone(user_tz)
        return local_date.strftime('%Y-%m-%d')
    except:
        return str(date_string).split('T')[0]

def get_hr_pending_requests():
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
        st.error(f"Error getting HR pending requests: {e}")
        return pd.DataFrame()

def set_hr_decision_new(hr_id, request_id, approve):
    """Set HR decision - UPDATED VERSION dengan change_off_days"""
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
                else:
                    # Create new quota if doesn't exist
                    cursor.execute("""
                        INSERT INTO quotas (user_id, year, leave_total, leave_used, changeoff_earned, changeoff_used, created_at, updated_at)
                        VALUES (?, ?, 12, ?, 0, 0, ?, ?)
                    """, (user_id, year, days, now, now))
                
            elif request["type"] == "CHANGEOFF":
                # PERBAIKAN: Gunakan change_off_days dengan aturan baru
                if request["change_off_days"] and request["change_off_days"] > 0:
                    # Gunakan perhitungan baru: setiap hari > 8 jam = 1 hari change off
                    days_earned = request["change_off_days"]
                else:
                    # Fallback ke perhitungan lama untuk data existing
                    hours = request["hours"] if request["hours"] is not None else 0
                    days_earned = int(hours / 8) if hours > 0 else 0
                
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
            
            elif request["type"] == "LEAVE" and request["reason"] == "CHANGEOFF":
                # Handle CHANGEOFF reason in LEAVE type - deduct changeoff balance
                start_date = datetime.fromisoformat(request["start_date"]).date()
                end_date = datetime.fromisoformat(request["end_date"]).date()
                days = (end_date - start_date).days + 1
                
                cursor.execute("SELECT * FROM quotas WHERE user_id = ? AND year = ?", (user_id, year))
                quota = cursor.fetchone()
                
                if quota:
                    new_co_used = quota["changeoff_used"] + days
                    cursor.execute("""
                        UPDATE quotas 
                        SET changeoff_used = ?, updated_at = ?
                        WHERE user_id = ? AND year = ?
                    """, (new_co_used, now, user_id, year))
                else:
                    # Create new quota if doesn't exist
                    cursor.execute("""
                        INSERT INTO quotas (user_id, year, leave_total, leave_used, changeoff_earned, changeoff_used, created_at, updated_at)
                        VALUES (?, ?, 12, 0, 0, ?, ?, ?)
                    """, (user_id, year, days, now, now))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        st.error(f"Error setting HR decision: {e}")
        return False

def update_user_sick_balance(user_id, new_balance):
    """Update user sick balance"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET sick_balance = ?, updated_at = ?
            WHERE id = ?
        """, (new_balance, datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating sick balance: {e}")
        return False

# ==============================================
# PAGE FUNCTIONS
# ==============================================
def page_hr_users(user):
    st.markdown('<div class="main-header">👥 Users Management</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search_name = st.text_input("🔍 Search user by name...", placeholder="Enter name to search", key="search_user_name")
    with col2:
        show_add_form = st.button("➕ Add User", key="btn_show_add_user", use_container_width=True)
        if show_add_form:
            st.session_state["show_add_form"] = True
            st.query_params["scroll"] = "adduserform"
    with col3:
        if st.button("🔄 Refresh Data", key="btn_refresh_users", use_container_width=True):
            st.rerun()
    users_df = list_users()
    st.markdown("### 🏢 Filter by Division")
    all_divisions = users_df['division'].dropna().unique().tolist()
    all_divisions.sort()
    cols = st.columns(min(6, len(all_divisions) + 2))
    with cols[0]:
        if st.button("👥 All Divisions", key="btn_all_divisions", use_container_width=True):
            st.session_state.selected_division = "ALL"
            st.rerun()
    for i, division in enumerate(all_divisions, 1):
        if i < len(cols):
            with cols[i]:
                if st.button(f"🏢 {division}", key=f"btn_division_{division}", use_container_width=True):
                    st.session_state.selected_division = division
                    st.rerun()
    selected_division = st.session_state.get('selected_division', 'ALL')
    if selected_division != "ALL":
        users_df = users_df[users_df['division'] == selected_division]
        st.markdown(f'<div class="success-banner">📊 Showing users from: <strong>{selected_division}</strong> division</div>', unsafe_allow_html=True)
    if search_name:
        users_df = users_df[users_df["name"].str.contains(search_name, case=False, na=False)]
    st.markdown("### 📊 User Statistics")
    total_users = len(users_df)
    managers_count = len(users_df[users_df["role"] == "MANAGER"])
    hr_count = len(users_df[users_df["role"] == "HR_ADMIN"])
    employee_count = len(users_df[users_df["role"] == "EMPLOYEE"])
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="metric-card"><h3>👥 Total Users</h3><h2>{total_users}</h2></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><h3>👔 Managers</h3><h2>{managers_count}</h2></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><h3>📋 HR Admins</h3><h2>{hr_count}</h2></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><h3>💼 Employees</h3><h2>{employee_count}</h2></div>', unsafe_allow_html=True)

    if st.session_state.get("show_add_form", False):
        st.markdown('<a id="adduserform"></a>', unsafe_allow_html=True)
        st.markdown("""
            <script>
            (function() {
                try {
                    const params = new URLSearchParams(window.location.search);
                    if (params.get("scroll") === "adduserform") {
                        setTimeout(function() {
                            var el = document.getElementById("adduserform");
                            if (el) el.scrollIntoView({behavior: "smooth", block: "start"});
                        }, 200);
                    }
                } catch(e) {}
            })();
            </script>
        """, unsafe_allow_html=True)
        st.markdown('<div class="sub-header">➕ Add New User</div>', unsafe_allow_html=True)
        with st.form("add_user_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Basic Information**")
                nik_new = st.text_input("NIK *", key="new_nik")
                email_new = st.text_input("Email *", key="new_email")
                name_new = st.text_input("Full Name *", key="new_name")
                role_new = st.selectbox("Role *", ["EMPLOYEE", "MANAGER", "HR_ADMIN"], key="new_role")
                division_new = st.text_input("Division", placeholder="e.g., Engineering, Marketing", key="new_division")
            with col2:
                st.markdown("**Employment Details**")
                join_date = st.date_input("Join Date", value=date(2025, 1, 1), min_value=date(1995, 1, 1), key="new_join_date")
                probation_date = st.date_input("Probation End Date", value=None, min_value=date(1995, 1, 1), key="new_probation_date")
                permanent_date = st.date_input("Permanent Date", value=None, min_value=date(1995, 1, 1), key="new_permanent_date")
                sick_balance_new = st.number_input("Sick Leave Balance (Max 6 days)", min_value=0, max_value=6, value=6, key="new_sick_balance",
                                                 help="Maximum 6 days sick leave without doctor's note")
            st.markdown("**Manager Assignment**")
            managers_df = list_managers()
            mgr_options = ["(No Manager)"] + [f"{r['name']} ({r['email']})" for _, r in managers_df.iterrows()]
            mgr_sel = st.selectbox("Manager", options=list(range(len(mgr_options))), format_func=lambda i: mgr_options[i], key="new_mgr")
            manager_id_new = None if mgr_sel == 0 else int(managers_df.iloc[int(mgr_sel) - 1]["id"])
            st.markdown("**Security**")
            password_new = st.text_input("Password *", type="password", key="new_password")
            col_save, col_cancel = st.columns(2)
            with col_save:
                submit = st.form_submit_button("💾 Save User", use_container_width=True)
            with col_cancel:
                cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
            if submit:
                if not all([nik_new, email_new, name_new, password_new]):
                    st.error("Please fill all required fields (*)")
                else:
                    try:
                        create_user(
                            email_new, name_new, role_new, password_new, manager_id_new,
                            division_new.strip() or None,
                            join_date.isoformat() if join_date else None,
                            probation_date.isoformat() if probation_date else None,
                            permanent_date.isoformat() if permanent_date else None,
                            sick_balance_new, nik_new
                        )
                        st.success("✅ User created successfully!")
                        st.session_state["show_add_form"] = False
                        if "scroll" in st.query_params:
                            del st.query_params["scroll"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
            if cancel:
                st.session_state["show_add_form"] = False
                if "scroll" in st.query_params:
                    del st.query_params["scroll"]
                st.rerun()

    st.markdown('<div class="sub-header">📋 Users List</div>', unsafe_allow_html=True)
    if users_df.empty:
        st.info("No users found.")
        return
    display_df = users_df.copy()
    display_df = display_df[['id', 'nik', 'name', 'email', 'role', 'division', 'sick_balance', 'manager_id']]
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "nik": st.column_config.TextColumn("NIK", width="small"),
            "name": st.column_config.TextColumn("Name", width="medium"),
            "email": st.column_config.TextColumn("Email", width="medium"),
            "role": st.column_config.TextColumn("Role", width="small"),
            "division": st.column_config.TextColumn("Division", width="medium"),
            "sick_balance": st.column_config.NumberColumn("Sick Days", width="small"),
            "manager_id": st.column_config.NumberColumn("Manager ID", width="small"),
        }
    )
    st.markdown('<div class="sub-header">⚙️ Manage Users</div>', unsafe_allow_html=True)
    users_df2 = list_users()
    if selected_division != "ALL":
        users_df2 = users_df2[users_df2['division'] == selected_division]
    if search_name:
        users_df2 = users_df2[users_df2["name"].str.contains(search_name, case=False, na=False)]
    if "show_delete_confirm" not in st.session_state:
        st.session_state["show_delete_confirm"] = False
    if "delete_user_id" not in st.session_state:
        st.session_state["delete_user_id"] = None
    if "delete_user_name" not in st.session_state:
        st.session_state["delete_user_name"] = ""
    for idx, user_data in users_df2.iterrows():
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"""
                <div class="user-card">
                    <h3>👤 {user_data['name']}</h3>
                    <p><strong>Email:</strong> {user_data['email']}</p>
                    <p><strong>Role:</strong> {user_data['role']} • <strong>Division:</strong> {user_data.get('division', '-')}</p>
                    <p><strong>Sick Balance:</strong> <span class="sick-balance-badge">{user_data.get('sick_balance', 6)} days</span></p>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                if st.button("✏️ Edit", key=f"edit_{user_data['id']}", use_container_width=True):
                    st.session_state[f"edit_user_{user_data['id']}"] = True
                    st.rerun()
            with col3:
                if st.button("🗑️ Delete", key=f"delete_{user_data['id']}", use_container_width=True, type="secondary"):
                    if int(user_data["id"]) == int(user["id"]):
                        st.error("❌ Cannot delete your own account!")
                    else:
                        st.session_state["show_delete_confirm"] = True
                        st.session_state["delete_user_id"] = int(user_data["id"])
                        st.session_state["delete_user_name"] = user_data["name"]
                        st.rerun()
            if st.session_state.get("show_delete_confirm", False) and st.session_state.get("delete_user_id") == int(user_data["id"]):
                st.warning(f"⚠️ Konfirmasi hapus user **{st.session_state['delete_user_name']}**?")
                col_yes, col_no = st.columns([1,1])
                with col_yes:
                    if st.button("Ya, Hapus", key=f"confirm_delete_{user_data['id']}", use_container_width=True):
                        with st.spinner("Deleting user..."):
                            if delete_user_force(int(user_data["id"])):
                                st.success("✅ User deleted successfully!")
                            else:
                                st.error("❌ Failed to delete user.")
                        st.session_state["show_delete_confirm"] = False
                        st.session_state["delete_user_id"] = None
                        st.session_state["delete_user_name"] = ""
                        st.rerun()
                with col_no:
                    if st.button("Batal", key=f"cancel_delete_{user_data['id']}", use_container_width=True):
                        st.session_state["show_delete_confirm"] = False
                        st.session_state["delete_user_id"] = None
                        st.session_state["delete_user_name"] = ""
            if st.session_state.get(f"edit_user_{user_data['id']}", False):
                with st.expander(f"✏️ Editing {user_data['name']}", expanded=True):
                    with st.form(f"edit_form_{user_data['id']}"):
                        st.markdown("**Edit User Details**")
                        col1, col2 = st.columns(2)
                        with col1:
                            edit_nik = st.text_input("NIK", value=user_data.get("nik", ""), key=f"edit_nik_{user_data['id']}")
                            edit_email = st.text_input("Email", value=user_data["email"], key=f"edit_email_{user_data['id']}")
                            edit_name = st.text_input("Name", value=user_data["name"], key=f"edit_name_{user_data['id']}")
                            edit_role = st.selectbox("Role", ["EMPLOYEE", "MANAGER", "HR_ADMIN"],
                                                   index=["EMPLOYEE", "MANAGER", "HR_ADMIN"].index(user_data["role"]),
                                                   key=f"edit_role_{user_data['id']}")
                            edit_division = st.text_input("Division", value=user_data.get("division") or "", key=f"edit_division_{user_data['id']}")
                        with col2:
                            current_join_date = user_data.get("join_date")
                            edit_join_date = st.date_input("Join Date",
                                                         value=pd.to_datetime(current_join_date).date() if current_join_date else None,
                                                         min_value=date(1995, 1, 1),
                                                         key=f"edit_join_date_{user_data['id']}")
                            current_probation_date = user_data.get("probation_date")
                            edit_probation_date = st.date_input("Probation End Date",
                                                              value=pd.to_datetime(current_probation_date).date() if current_probation_date else None,
                                                              min_value=date(1995, 1, 1),
                                                              key=f"edit_probation_date_{user_data['id']}")
                            current_permanent_date = user_data.get("permanent_date")
                            edit_permanent_date = st.date_input("Permanent Date",
                                                              value=pd.to_datetime(current_permanent_date).date() if current_permanent_date else None,
                                                              min_value=date(1995, 1, 1),
                                                              key=f"edit_permanent_date_{user_data['id']}")
                            current_sick_balance = user_data.get("sick_balance", 6)
                            edit_sick_balance = st.number_input("Sick Leave Balance (Max 6 days)",
                                                              min_value=0, max_value=6, value=int(current_sick_balance) if current_sick_balance else 6,
                                                              key=f"edit_sick_balance_{user_data['id']}",
                                                              help="Maximum 6 days sick leave without doctor's note")
                        managers_df = list_managers()
                        mgr_options = ["(No Manager)"] + [f"{r['name']} ({r['email']})" for _, r in managers_df.iterrows() if r["id"] != user_data["id"]]
                        current_mgr_id = user_data["manager_id"]
                        current_idx = 0
                        if not pd.isna(current_mgr_id) and current_mgr_id is not None:
                            current_mgr_id = int(current_mgr_id)
                            manager_ids = [int(r["id"]) for _, r in managers_df.iterrows()]
                            if current_mgr_id in manager_ids:
                                current_idx = 1 + manager_ids.index(current_mgr_id)
                        sel_mgr_idx = st.selectbox("Manager", options=list(range(len(mgr_options))), index=current_idx,
                                                 format_func=lambda i: mgr_options[i], key=f"edit_mgr_{user_data['id']}")
                        edit_manager_id = None if sel_mgr_idx == 0 else int(managers_df.iloc[int(sel_mgr_idx) - 1]["id"])
                        new_pw = st.text_input("Reset Password (optional)", type="password", key=f"edit_pw_{user_data['id']}")
                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            submit_edit = st.form_submit_button("💾 Save Changes", use_container_width=True)
                        with col_cancel:
                            cancel_edit = st.form_submit_button("❌ Cancel", use_container_width=True)
                        if submit_edit:
                            try:
                                update_user(
                                    int(user_data["id"]), edit_email, edit_name, edit_role, edit_manager_id,
                                    new_pw if new_pw else None, edit_division.strip() or None,
                                    edit_join_date.isoformat() if edit_join_date else None,
                                    edit_probation_date.isoformat() if edit_probation_date else None,
                                    edit_permanent_date.isoformat() if edit_permanent_date else None,
                                    edit_sick_balance, edit_nik
                                )
                                st.success("✅ User updated successfully!")
                                st.session_state[f"edit_user_{user_data['id']}"] = False
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {str(e)}")
                        if cancel_edit:
                            st.session_state[f"edit_user_{user_data['id']}"] = False
                            st.rerun()

def page_hr_quotas(user):
    """Halaman management quotas dan sick balance"""
    st.markdown('<div class="main-header">📊 Quotas & Sick Balance Management</div>', unsafe_allow_html=True)
    
    users_df = list_users()
    if users_df.empty:
        st.info("No users found.")
        return

    # --- Division Filter ---
    st.markdown("### 🏢 Filter by Division")
    all_divisions = users_df['division'].dropna().unique().tolist()
    all_divisions.sort()
    
    col_div_buttons = st.columns(min(6, len(all_divisions) + 2))
    with col_div_buttons[0]:
        if st.button("👥 All", key="btn_all_divisions_quota", use_container_width=True):
            st.session_state.selected_division_quota = "ALL"
            st.rerun()

    for i, division in enumerate(all_divisions, 1):
        if i < len(col_div_buttons):
            with col_div_buttons[i]:
                if st.button(f"🏢 {division}", key=f"btn_division_quota_{division}", use_container_width=True):
                    st.session_state.selected_division_quota = division
                    st.rerun()

    selected_division = st.session_state.get('selected_division_quota', 'ALL')
    if selected_division != "ALL":
        users_df = users_df[users_df['division'] == selected_division]
        st.success(f"📊 Showing quotas from: {selected_division} division")

    # Quota Statistics
    st.markdown("### 📈 Quota Statistics")
    total_leave = 0
    total_used = 0
    total_co_earned = 0
    total_co_used = 0
    total_sick_balance = 0

    for _, u in users_df.iterrows():
        q = user_quota(int(u["id"]), current_year())
        total_leave += int(q["leave_total"])
        total_used += int(q["leave_used"])
        total_co_earned += int(q["co_earned"])
        total_co_used += int(q["co_used"])
        total_sick_balance += int(u.get("sick_balance", 6))

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(f'<div class="metric-card"><h3>📅 Total Leave</h3><h2>{total_leave}</h2></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><h3>✅ Leave Used</h3><h2>{total_used}</h2></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><h3>🔄 CO Earned</h3><h2>{total_co_earned}</h2></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><h3>⏹️ CO Used</h3><h2>{total_co_used}</h2></div>', unsafe_allow_html=True)
    with col5:
        st.markdown(f'<div class="metric-card"><h3>🤒 Total Sick Days</h3><h2>{total_sick_balance}</h2></div>', unsafe_allow_html=True)

    st.markdown("---")

    # User Selection for Quota Management
    st.markdown("### 👥 Manage User Quotas & Sick Balance")
    display = users_df.apply(lambda r: f"{r['name']} ({r['email']}) [{r['role']}] • {r.get('division','-')}", axis=1).tolist()
    if not display:
        st.info("No users in selected division.")
        return

    idx = st.selectbox("Select User", options=list(range(len(display))), format_func=lambda i: display[i], key="user_select_hr")
    selected_user = users_df.iloc[int(idx)]
    user_id = int(selected_user["id"])
    year = st.number_input("Year", min_value=1995, max_value=2100, value=current_year(), step=1, key="year_select_hr")

    q = user_quota(user_id, year)
    
    # Add sick balance to quota display
    q['sick_balance'] = selected_user.get('sick_balance', 6)

    # Display quota kanban
    quota_kanban(q)

    # Edit Quota & Sick Balance Form
    st.markdown("### ✏️ Edit Quotas & Sick Balance")
    with st.form("edit_quota_form"):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            leave_total = st.number_input("Leave Total", min_value=0, value=int(q["leave_total"]), step=1, key="qt_leave_total")
            leave_used = st.number_input("Leave Used", min_value=0, value=int(q["leave_used"]), step=1, key="qt_leave_used")
        
        with col2:
            co_earned = st.number_input("ChangeOff Earned", min_value=0, value=int(q["co_earned"]), step=1, key="qt_co_earned")
            co_used = st.number_input("ChangeOff Used", min_value=0, value=int(q["co_used"]), step=1, key="qt_co_used")
        
        with col3:
            sick_balance = st.number_input(
                "Sick Balance (Max 6 days)", 
                min_value=0, max_value=6, 
                value=int(q.get('sick_balance', 6)), 
                step=1, 
                key="qt_sick_balance",
                help="Sick leave without doctor's note"
            )
        
        with col4:
            st.markdown("**Actions**")
            st.info(f"**User:** {selected_user['name']}\n**Division:** {selected_user.get('division', '-')}\n**Year:** {year}")

        col_save, col_del, _ = st.columns([1, 1, 2])
        
        with col_save:
            save_quota = st.form_submit_button("💾 Save All Changes", use_container_width=True)
        
        with col_del:
            delete_quota_btn = st.form_submit_button("🗑️ Delete Quota", use_container_width=True)

        if save_quota:
            try:
                # Save quota
                upsert_quota(user_id, year, int(leave_total), int(co_earned), int(co_used), int(leave_used))
                # Save sick balance
                update_user_sick_balance(user_id, int(sick_balance))
                st.success("✅ Quota and Sick Balance saved successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
        
        if delete_quota_btn:
            try:
                delete_quota(user_id, year)
                st.warning("⚠️ Quota for this year deleted!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    st.markdown("---")

    # Bulk Operations
    st.markdown("### ⚡ Bulk Operations")
    col_reset1, col_reset2 = st.columns(2)
    
    with col_reset1:
        st.markdown("### 🔼 Add Balance")
        with st.form("incremental_reset_form"):
            st.info("Add 1 leave balance to all users")
            reset_year_inc = st.number_input("Year", min_value=1995, max_value=2100, value=current_year(), key="reset_year_inc")
            increment_btn = st.form_submit_button("➕ Add 1 Balance to All Users", use_container_width=True)
            
            if increment_btn:
                try:
                    result = hr_reset_quotas_incremental(reset_year_inc)
                    st.success(f"✅ Added 1 balance to {result['updated_count']} users!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    with col_reset2:
        st.markdown("### 🔄 Reset to Zero")
        with st.form("zero_reset_form"):
            st.warning("Reset all quotas to zero")
            reset_year_zero = st.number_input("Reset Year", min_value=1995, max_value=2100, value=current_year(), key="reset_year_zero")
            reset_zero_btn = st.form_submit_button("🔄 Reset All Quotas to Zero", use_container_width=True, type="secondary")
            
            if reset_zero_btn:
                try:
                    result = hr_reset_quotas_to_zero(reset_year_zero)
                    st.success(f"✅ Reset quotas for {result} users!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")

def page_hr_pending(user):
    """Halaman pending approval untuk HR"""
    st.markdown('<div class="main-header">Pending Approval (HR)</div>', unsafe_allow_html=True)
    
    df = get_hr_pending_requests()
    
    if df.empty:
        st.success("🎉 Tidak ada request menunggu persetujuan HR.")
        return

    # Tampilkan statistik
    pending_count = len(df[df["status"] == "PENDING_HR"])
    approved_count = len(df[df["status"] == "APPROVED"]) 
    rejected_count = len(df[df["status"] == "REJECTED"])
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Menunggu Persetujuan", pending_count)
    with col2:
        st.metric("Telah Disetujui", approved_count)
    with col3:
        st.metric("Telah Ditolak", rejected_count)

    st.markdown("---")

    # Filter berdasarkan status
    status_filter = st.selectbox(
        "Filter Status",
        options=["SEMUA", "PENDING_HR", "APPROVED", "REJECTED"],
        index=0
    )
    
    if status_filter != "SEMUA":
        df = df[df["status"] == status_filter]

    for _, r in df.iterrows():
        # Tentukan ikon berdasarkan status
        if r["status"] == "PENDING_HR":
            status_icon = "⏳"
        elif r["status"] == "APPROVED":
            status_icon = "✅"
        else:
            status_icon = "❌"

        # Tampilkan card untuk setiap request
        with st.expander(f"{status_icon} {r['type']} - {r['employee_name']} (Div: {r.get('employee_division','-')})", expanded=False):
            
            # Tampilkan informasi request - CONVERT SEMUA KE STRING
            request_data = {
                "Request ID": str(r["id"]),
                "Type": str(r["type"]),
                "Status": str(r["status"]),
                "Created At (WIB)": convert_to_local_time(r["created_at"]),
                "Updated At (WIB)": convert_to_local_time(r["updated_at"]),
                "Employee Name": str(r.get("employee_name", "")),
                "Division": str(r.get("employee_division", "-"))
            }
            
            if r["type"] == "LEAVE":
                request_data.update({
                    "Start Date": format_date_for_display(r.get("start_date", "")),
                    "End Date": format_date_for_display(r.get("end_date", "")),
                    "Reason": str(r.get("reason", "")),
                    "Keterangan": str(r.get("keterangan", "-"))
                })
                
                # Show balance impact for LEAVE requests
                if r.get("reason") == "PERSONAL":
                    start_date = datetime.fromisoformat(r["start_date"]).date()
                    end_date = datetime.fromisoformat(r["end_date"]).date()
                    days = (end_date - start_date).days + 1
                    st.info(f"💡 **Impact:** Will deduct {days} days from leave balance")
                elif r.get("reason") == "CHANGEOFF":
                    start_date = datetime.fromisoformat(r["start_date"]).date()
                    end_date = datetime.fromisoformat(r["end_date"]).date()
                    days = (end_date - start_date).days + 1
                    st.info(f"💡 **Impact:** Will deduct {days} days from change-off balance")
                elif r.get("reason") == "SICK":
                    st.info("💡 **Impact:** No balance deduction (sick leave with doctor's note)")
                elif r.get("reason") == "UNPAID_LEAVE":
                    st.info("💡 **Impact:** No balance deduction (unpaid leave)")
                    
            else:  # CHANGEOFF
                # Handle both departure_date/return_date and start_date/end_date
                departure = r.get("departure_date") or r.get("start_date", "")
                return_d = r.get("return_date") or r.get("end_date", "")
                hours = r.get("hours", 0)
                
                # PERBAIKAN: Gunakan change_off_days dengan aturan baru
                change_off_days = r.get("change_off_days", 0)
                if change_off_days and change_off_days > 0:
                    days_earned = change_off_days
                    impact_text = f"Will add {days_earned} days to change-off balance (based on {days_earned} days with activities > 8 hours)"
                    calculation_method = "NEW: Days with >8h activities"
                else:
                    # Fallback untuk data lama
                    days_earned = int(hours / 8) if hours and hours > 0 else 0
                    impact_text = f"Will add {days_earned} days to change-off balance ({hours} hours ÷ 8 - Legacy calculation)"
                    calculation_method = "OLD: Total hours ÷ 8"
                
                request_data.update({
                    "Departure Date": format_date_for_display(departure),
                    "Return Date": format_date_for_display(return_d),
                    "Total Hours": str(hours),
                    "Change Off Days": str(change_off_days) if change_off_days > 0 else f"{days_earned} (calculated)",
                    "Calculation Method": calculation_method,
                    "Location": str(r.get("location", "")),
                    "PIC": str(r.get("pic", "")),
                    "Keterangan": str(r.get("keterangan", "-"))
                })
                
                # Show balance impact for CHANGEOFF requests
                st.info(f"💡 **Impact:** {impact_text}")

            # Tampilkan sebagai dataframe
            st.dataframe(pd.DataFrame.from_dict(request_data, orient='index', columns=['Value']),
                        use_container_width=True)
            
            # Tampilkan detail aktivitas untuk CHANGEOFF
            if r["type"] == "CHANGEOFF" and r.get('activities_json') and r['activities_json'] not in ['null', None]:
                try:
                    activities_json = json.loads(r['activities_json'])
                    if activities_json:
                        st.subheader("📋 Detail Aktivitas")
                        activities_df = pd.DataFrame(activities_json)
                        activities_df['hari'] = activities_df.index + 1
                        
                        # Add calculation of hours per day and change off eligibility
                        if 'waktu_mulai' in activities_df.columns and 'waktu_selesai' in activities_df.columns:
                            def calculate_hours(row):
                                try:
                                    start = datetime.strptime(row['waktu_mulai'], '%H:%M')
                                    end = datetime.strptime(row['waktu_selesai'], '%H:%M')
                                    if end < start:
                                        end = end.replace(day=end.day + 1)
                                    hours = (end - start).total_seconds() / 3600
                                    return hours
                                except:
                                    return 0
                            
                            activities_df['jam_kerja'] = activities_df.apply(calculate_hours, axis=1)
                            activities_df['dapat_co'] = activities_df['jam_kerja'].apply(lambda x: "✅ Ya" if x > 8 else "❌ Tidak")
                        
                        if 'tanggal' in activities_df.columns:
                            activities_df['tanggal_dt'] = pd.to_datetime(activities_df['tanggal'])
                            day_mapping = {
                                'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
                                'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu', 'Sunday': 'Minggu'
                            }
                            activities_df['hari_nama'] = activities_df['tanggal_dt'].dt.strftime('%A').map(day_mapping)
                            activities_df['tanggal'] = activities_df['hari_nama'] + ', ' + activities_df['tanggal_dt'].dt.strftime('%Y-%m-%d')
                            activities_df = activities_df.drop(['tanggal_dt', 'hari_nama'], axis=1)
                        
                        columns_to_show = ['hari']
                        if 'tanggal' in activities_df.columns: columns_to_show.append('tanggal')
                        if 'waktu_mulai' in activities_df.columns: columns_to_show.append('waktu_mulai')
                        if 'waktu_selesai' in activities_df.columns: columns_to_show.append('waktu_selesai')
                        if 'jam_kerja' in activities_df.columns: columns_to_show.append('jam_kerja')
                        if 'dapat_co' in activities_df.columns: columns_to_show.append('dapat_co')
                        if 'aktivitas' in activities_df.columns: columns_to_show.append('aktivitas')
                        
                        st.dataframe(activities_df[columns_to_show], use_container_width=True, hide_index=True)
                        
                        # Summary
                        if 'dapat_co' in activities_df.columns:
                            eligible_days = len(activities_df[activities_df['dapat_co'] == "✅ Ya"])
                            st.success(f"📊 **Summary:** {eligible_days} hari dengan aktivitas > 8 jam = {eligible_days} hari change off")
                        
                except Exception as e:
                    st.error(f"Error menampilkan data aktivitas: {e}")

            # Tampilkan file jika ada
            if r.get('file_uploaded', 0) and r.get('timesheet_path'):
                st.info("📎 Attached File:")
                preview_file(r['timesheet_path'], key_prefix=f"hr_req_{r['id']}", user_role=user["role"])

            # Tombol Approve/Reject hanya untuk status pending
            if r["status"] == "PENDING_HR":
                st.markdown("---")
                c1, c2 = st.columns(2)
                
                with c1:
                    if st.button(f"✅ Approve", key=f"hr_appr_{r['id']}", use_container_width=True):
                        if set_hr_decision_new(int(user["id"]), int(r["id"]), True):
                            st.success("✅ Approved. Saldo telah diupdate.")
                            st.rerun()
                
                with c2:
                    if st.button(f"❌ Reject", key=f"hr_rej_{r['id']}", use_container_width=True):
                        if set_hr_decision_new(int(user["id"]), int(r["id"]), False):
                            st.warning("❌ Rejected.")
                            st.rerun()