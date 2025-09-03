import streamlit as st
import pandas as pd
import json
from file_utils import preview_file
from datetime import datetime
import pytz
from db import get_conn

# Fungsi konversi waktu (sama seperti di ui_employee.py)
def convert_to_local_time(utc_string, user_timezone='Asia/Jakarta'):
    """Konversi UTC time ke waktu lokal user"""
    if not utc_string:
        return ""
    try:
        utc_time = datetime.fromisoformat(utc_string.replace('Z', '+00:00'))
        user_tz = pytz.timezone(user_timezone)
        local_time = utc_time.astimezone(user_tz)
        return local_time.strftime('%Y-%m-%d %H:%M:%S (%Z)')
    except Exception as e:
        return f"{utc_string}"

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

def get_manager_pending_requests(manager_id):
    """Dapatkan pending requests untuk manager"""
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
        st.error(f"Error getting manager pending requests: {e}")
        return pd.DataFrame()

def set_manager_decision_new(manager_id, request_id, approve):
    """Set manager decision untuk request"""
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
        now = datetime.now(pytz.timezone('Asia/Jakarta')).isoformat()
        
        cursor.execute("""
            UPDATE requests 
            SET status = ?, manager_at = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, now, now, request_id))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        st.error(f"Error setting manager decision: {e}")
        return False

def page_manager_pending(user):
    """Halaman pending approval untuk manager"""
    st.header("Pending Approval (Manager)")
    
    df = get_manager_pending_requests(user["id"])
    
    if df.empty:
        st.info("Tidak ada request menunggu Manager.")
        return
    
    for _, r in df.iterrows():
        status_icon = "⏳" if "PENDING" in str(r["status"]) else "✅" if r["status"] == "APPROVED" else "❌"
        status_text = f"{status_icon} [{r['type']}] {r['employee_name']} • Div {r.get('employee_division','-')} • Status: {r['status']} • ID: {r['id']}"
        
        if r.get('file_uploaded', 0):
            status_text += " 📎"
        
        with st.expander(status_text, expanded=False):
            # TAMPILAN CONSISTENT SEPERTI MY REQUEST DI EMPLOYEE
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
            else:  # CHANGEOFF
                # Handle both departure_date/return_date and start_date/end_date
                departure = r.get("departure_date") or r.get("start_date", "")
                return_d = r.get("return_date") or r.get("end_date", "")
                hours = r.get("hours", 0)
                
                # PERBAIKAN: Gunakan change_off_days dengan aturan baru
                change_off_days = r.get("change_off_days", 0)
                if change_off_days and change_off_days > 0:
                    days_text = f"{change_off_days} days (activities > 8h/day)"
                    calculation_method = "NEW: Days with >8h activities"
                else:
                    days_text = f"{int(hours/8) if hours > 0 else 0} days ({hours}h ÷ 8 - legacy)"
                    calculation_method = "OLD: Total hours ÷ 8"
                
                request_data.update({
                    "Departure Date": format_date_for_display(departure),
                    "Return Date": format_date_for_display(return_d),
                    "Total Hours": str(hours),
                    "Change Off Earned": days_text,
                    "Calculation Method": calculation_method,
                    "Location": str(r.get("location", "")),
                    "PIC": str(r.get("pic", "")),
                    "Keterangan": str(r.get("keterangan", "-"))
                })

            # Tampilkan sebagai dataframe seperti di employee
            st.dataframe(pd.DataFrame.from_dict(request_data, orient='index', columns=['Value']),
                        use_container_width=True)

            # Tampilkan detail aktivitas jika ada (khusus changeoff)
            if r["type"] == "CHANGEOFF" and r.get('activities_json') and r['activities_json'] not in ['null', None]:
                try:
                    json_data = json.loads(r['activities_json'])
                    if json_data:
                        st.subheader("📋 Detail Aktivitas")
                        activities_df = pd.DataFrame(json_data)
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
                                    return round(hours, 1)
                                except:
                                    return 0
                            
                            activities_df['jam_kerja'] = activities_df.apply(calculate_hours, axis=1)
                            activities_df['dapat_co'] = activities_df['jam_kerja'].apply(lambda x: "✅ Ya (1 hari)" if x > 8 else "❌ Tidak")
                        
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
                        
                        # Summary dengan aturan baru
                        if 'dapat_co' in activities_df.columns:
                            eligible_days = len(activities_df[activities_df['dapat_co'].str.contains("✅")])
                            total_hours = activities_df['jam_kerja'].sum() if 'jam_kerja' in activities_df.columns else 0
                            st.success(f"📊 **New Calculation:** {eligible_days} hari dengan aktivitas > 8 jam = {eligible_days} hari change off")
                            st.info(f"📊 **Old Calculation:** {total_hours:.1f} jam total ÷ 8 = {int(total_hours/8)} hari change off")
                        
                except Exception as e:
                    st.error(f"Error menampilkan data aktivitas: {e}")

            # Tampilkan file jika ada
            if r.get('file_uploaded', 0) and r.get('timesheet_path'):
                st.info("📎 Attached File:")
                preview_file(r['timesheet_path'], key_prefix=f"mgr_req_{r['id']}", user_role=user["role"])

            # Tombol Approve/Reject
            c1, c2 = st.columns(2)
            with c1:
                if st.button(f"✅ Approve (ID {r['id']})", key=f"mgr_appr_{r['id']}"):
                    if set_manager_decision_new(int(user["id"]), int(r["id"]), True):
                        st.success("Approved → dikirim ke HR.")
                        st.rerun()
            with c2:
                if st.button(f"❌ Reject (ID {r['id']})", key=f"mgr_rej_{r['id']}"):
                    if set_manager_decision_new(int(user["id"]), int(r["id"]), False):
                        st.warning("Rejected.")
                        st.rerun()

def page_manager_team(user):
    """Halaman history team requests"""
    st.header("📊 HISTORY Team Requests")
    
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT r.*, u.name as employee_name, u.division as employee_division
        FROM requests r 
        JOIN users u ON u.id = r.user_id
        WHERE u.manager_id = ?
        ORDER BY r.created_at DESC
    """, conn, params=(user["id"],))
    conn.close()
    
    if df.empty:
        st.info("Belum ada request dari tim.")
        return

    # Filter options seperti di employee
    filter_type = st.selectbox("Filter by Type", ["ALL", "LEAVE", "CHANGEOFF"], key="mgr_filter_type")
    filter_status = st.selectbox("Filter by Status", ["ALL", "PENDING", "APPROVED", "REJECTED"], key="mgr_filter_status")

    # Apply filters
    if filter_type != "ALL":
        df = df[df["type"] == filter_type]
    if filter_status != "ALL":
        df = df[df["status"].str.contains(filter_status, case=False, na=False)]

    for _, r in df.iterrows():
        status_icon = "✅" if r["status"] == "APPROVED" else "⏳" if "PENDING" in str(r["status"]) else "❌"
        with st.expander(f"{status_icon} {r['type']} - {r['status']} - {r['employee_name']} - ID: {r['id']}", expanded=False):
            
            # TAMPILAN SAMA SEPERTI DI EMPLOYEE - CONVERT SEMUA KE STRING
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
            else:  # CHANGEOFF
                # Handle both departure_date/return_date and start_date/end_date
                departure = r.get("departure_date") or r.get("start_date", "")
                return_d = r.get("return_date") or r.get("end_date", "")
                hours = r.get("hours", 0)
                
                # PERBAIKAN: Gunakan change_off_days dengan aturan baru
                change_off_days = r.get("change_off_days", 0)
                if change_off_days and change_off_days > 0:
                    days_text = f"{change_off_days} days (NEW: activities > 8h)"
                else:
                    days_text = f"{int(hours/8) if hours > 0 else 0} days (OLD: {hours}h ÷ 8)"
                
                request_data.update({
                    "Departure Date": format_date_for_display(departure),
                    "Return Date": format_date_for_display(return_d),
                    "Total Hours": str(hours),
                    "Change Off Earned": days_text,
                    "Location": str(r.get("location", "")),
                    "PIC": str(r.get("pic", "")),
                    "Keterangan": str(r.get("keterangan", "-"))
                })

            # Tampilkan sebagai dataframe konsisten
            st.dataframe(pd.DataFrame.from_dict(request_data, orient='index', columns=['Value']),
                        use_container_width=True)

            # Tampilkan file jika ada
            if r.get('file_uploaded', 0) and r.get('timesheet_path'):
                st.info("📎 Attached File:")
                preview_file(r['timesheet_path'], key_prefix=f"mgr_hist_{r['id']}", user_role=user["role"])