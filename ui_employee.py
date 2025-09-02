import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
from business import (
    list_users, list_managers, create_user, update_user, delete_user,
    user_quota, upsert_quota, delete_quota, hr_pending, set_hr_decision,
    current_year, get_employees_by_manager, delete_user_force,
    hr_reset_quotas_incremental, hr_reset_quotas_to_zero
)
from file_utils import preview_file
import json
from db import get_conn
import pytz
from datetime import datetime
import time

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

def get_current_local_time():
    """Mendapatkan waktu sekarang dengan timezone Asia/Jakarta"""
    return datetime.now(pytz.timezone('Asia/Jakarta'))

def get_user_requests_history(user_id):
    """Fungsi untuk mendapatkan history requests user"""
    try:
        conn = get_conn()
        df = pd.read_sql_query("""
            SELECT r.*, u.name as employee_name, m.email as manager_email, m.name as manager_name
            FROM requests r
            JOIN users u ON r.user_id = u.id
            LEFT JOIN users m ON u.manager_id = m.id
            WHERE r.user_id = ?
            ORDER BY r.created_at DESC
        """, conn, params=(user_id,))
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error getting user requests: {e}")
        return pd.DataFrame()

def require_manager_assigned(user):
    """Check if user has manager assigned"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT manager_id FROM users WHERE id = ?", (user["id"],))
        result = cursor.fetchone()
        conn.close()
        
        if not result or not result["manager_id"]:
            st.error("❌ Anda belum memiliki Manager yang ditugaskan. Silakan hubungi HR untuk mengatur Manager Anda.")
            return False
        return True
    except Exception as e:
        st.error(f"Error checking manager assignment: {e}")
        return False

def get_sick_balance(user_id):
    """Dapatkan saldo sakit user"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT sick_balance FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result["sick_balance"] if result else 6
    except Exception as e:
        print(f"Error getting sick balance: {e}")
        return 6

def get_user_profile(user_id):
    """Mendapatkan data profil user termasuk NIK dan tanggal-tanggal penting"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT nik, join_date, probation_date, permanent_date, sick_balance, division FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "nik": row["nik"] if row["nik"] else "Belum diisi HR",
                "join_date": format_date_for_display(row["join_date"]) if row["join_date"] else "Belum diisi HR",
                "probation_date": format_date_for_display(row["probation_date"]) if row["probation_date"] else "Belum diisi HR",
                "permanent_date": format_date_for_display(row["permanent_date"]) if row["permanent_date"] else "Belum diisi HR",
                "sick_balance": row["sick_balance"] if row["sick_balance"] is not None else 6,
                "division": row["division"] if row["division"] else "-"
            }
        return {}
    except Exception as e:
        st.error(f"Error getting user profile: {e}")
        return {}

def quota_kanban(q: dict, title_prefix: str = ""):
    """Display quota information in kanban style"""
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.expander(f"{title_prefix} Leave • {q['leave_balance']}/{q['leave_total']} sisa", expanded=True):
            st.metric("Leave Balance", q["leave_balance"], delta=-q["leave_used"])
            st.write(f"Total: {q['leave_total']} | Used: {q['leave_used']}")
    with c2:
        with st.expander(f"{title_prefix} ChangeOff • {q['co_balance']} saldo", expanded=True):
            st.metric("CO Balance", q["co_balance"], delta=q["co_earned"] - q["co_used"])
            st.write(f"Earned: {q['co_earned']} | Used: {q['co_used']}")
    with c3:
        with st.expander(f"Sakit Tanpa Surat • {q.get('sick_balance', 6)}/{q.get('sick_balance', 6)} sisa", expanded=True):
            st.metric("Sakit Balance", q.get('sick_balance', 6))
            st.write(f"Maksimal: {q.get('sick_balance', 6)} hari tanpa surat dokter")
    with c4:
        with st.expander(f"Tahun {q['year']}", expanded=True):
            st.write("- Leave dipotong saat HR approve")
            st.write("- ChangeOff bertambah (jam/8) saat HR approve")
            st.write(f"- Sakit tanpa surat: {q.get('sick_balance', 6)} hari")

# ==============================================
# PAGE FUNCTIONS
# ==============================================

def page_employee_dashboard(user):
    """Dashboard karyawan dengan informasi kuota dan saldo"""
    st.markdown('<div class="main-header">Dashboard Karyawan</div>', unsafe_allow_html=True)
    
    # Dapatkan kuota dan saldo sakit
    year = current_year()
    quota = user_quota(int(user["id"]), year)
    sick_balance = get_sick_balance(int(user["id"]))
    
    # Tampilkan metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Saldo Cuti", quota["leave_balance"])
    with col2:
        st.metric("Saldo ChangeOff", quota["co_balance"])
    with col3:
        st.metric("Saldo Sakit", sick_balance,
                 help="Sakit tanpa surat dokter (maks 6 hari/tahun)")
    with col4:
        total_leave = quota["leave_total"] or 12
        used_percentage = (quota["leave_used"] / total_leave * 100) if total_leave > 0 else 0
        st.metric("Cuti Terpakai", f"{quota['leave_used']}/{total_leave} ({used_percentage:.1f}%)")
    
    st.markdown("---")
    
    # Tampilkan detail kuota
    st.subheader("📊 Detail Kuota")
    quota_data = {
        "Tipe Kuota": ["Cuti Tahunan", "Cuti Terpakai", "Sisa Cuti",
                      "ChangeOff Diperoleh", "ChangeOff Digunakan", "Sisa ChangeOff",
                      "Saldo Sakit"],
        "Jumlah": [quota["leave_total"], quota["leave_used"], quota["leave_balance"],
                  quota["co_earned"], quota["co_used"], quota["co_balance"],
                  sick_balance],
        "Keterangan": ["Total cuti tahun ini", "Cuti yang sudah digunakan", "Sisa cuti yang bisa digunakan",
                      "ChangeOff yang diperoleh", "ChangeOff yang digunakan", "Sisa ChangeOff",
                      "Sakit tanpa surat dokter"]
    }
    quota_df = pd.DataFrame(quota_data)
    st.dataframe(quota_df, hide_index=True, use_container_width=True)
    
    # Progress bars
    st.markdown("---")
    st.subheader("📈 Progress Penggunaan")
    
    # Progress bar cuti
    leave_used_percent = (quota["leave_used"] / quota["leave_total"] * 100) if quota["leave_total"] > 0 else 0
    st.write("**Cuti Tahunan**")
    st.progress(min(leave_used_percent / 100, 1.0),
               text=f"{quota['leave_used']}/{quota['leave_total']} ({leave_used_percent:.1f}%)")
    
    # Progress bar sakit
    sick_used = 6 - sick_balance
    sick_percent = (sick_used / 6 * 100) if sick_balance >= 0 else 100
    st.write("**Sakit Tanpa Surat Dokter**")
    st.progress(min(sick_percent / 100, 1.0),
               text=f"{sick_used}/6 ({sick_percent:.1f}%) - Sisa: {sick_balance} hari")

def page_submit_leave(user):
    """Form pengajuan cuti/izin"""
    st.header("Form Pengajuan Cuti/Izin")
    
    # Sidebar untuk history requests
    st.sidebar.subheader("History Pengajuan")
    df_history = get_user_requests_history(user["id"])
    
    if not df_history.empty:
        for idx, req in df_history.iterrows():
            status_icon = "✅" if req["status"] == "APPROVED" else "⏳" if "PENDING" in req["status"] else "❌"
            st.sidebar.info(f"{status_icon} {req['type']} - {req['status']}\n"
                           f"Tanggal: {format_date_for_display(req.get('start_date', req.get('departure_date', '')))}\n"
                           f"Status: {req['status']}")
    else:
        st.sidebar.info("Belum ada history pengajuan")
    
    # Pilihan reason
    reason_options = {
        "SICK": "Sakit (Dengan Surat Dokter)",
        "PERSONAL": "Cuti Personal",
        "CHANGEOFF": "Change Off (Tukar Shift - Potong Saldo)",
        "UNPAID_LEAVE": "Unpaid Leave"
    }
    
    selected_reason = st.selectbox(
        "Reason*",
        options=list(reason_options.keys()),
        format_func=lambda x: reason_options[x],
        key="reason_select_leave"
    )
    
    # Info berdasarkan reason yang dipilih
    if selected_reason == "CHANGEOFF":
        st.info("🔁 **Change Off (Tukar Shift):** Akan memotong saldo Change Off Anda setelah disetujui HR")
    elif selected_reason == "PERSONAL":
        st.info("🏖️ **Cuti Personal:** Akan memotong saldo cuti tahunan Anda setelah disetujui HR")
    elif selected_reason == "SICK":
        st.info("🤒 **Sakit:** Membutuhkan surat dokter, tidak memotong saldo cuti")
    elif selected_reason == "UNPAID_LEAVE":
        st.info("💸 **Unpaid Leave:** Cuti tanpa bayaran, tidak memotong saldo cuti")
    
    st.markdown("---")
    st.subheader("Detail Periode Cuti/Izin")
    
    col3, col4 = st.columns(2)
    with col3:
        start_date = st.date_input("Tanggal Mulai*", date.today(), key="start_date_leave")
    with col4:
        end_date = st.date_input("Tanggal Akhir*", date.today(), key="end_date_leave")
    
    # Hitung total hari
    total_days = 0
    if start_date and end_date:
        total_days = (end_date - start_date).days + 1
        if total_days > 0:
            st.info(f"Total hari: {total_days} hari")
            
            # Tampilkan info saldo berdasarkan reason
            q = user_quota(user["id"], start_date.year)
            if selected_reason == "CHANGEOFF":
                st.info(f"Saldo Change Off Anda: {q['co_balance']} hari")
                if q['co_balance'] < total_days:
                    st.warning(f"⚠️ Saldo Change Off tidak cukup untuk {total_days} hari")
            elif selected_reason == "PERSONAL":
                st.info(f"Saldo Cuti Anda: {q['leave_balance']} hari")
                if q['leave_balance'] < total_days:
                    st.warning(f"⚠️ Saldo cuti tidak cukup untuk {total_days} hari")
        else:
            st.error("Tanggal akhir harus setelah tanggal mulai")
    
    # Input keterangan
    st.markdown("---")
    st.subheader("Informasi Tambahan")
    keterangan = st.text_area("Keterangan (Opsional)",
                             placeholder="Tambahkan keterangan atau catatan tambahan untuk pengajuan ini...",
                             height=100,
                             help="Contoh: 'Butuh cuti untuk keperluan keluarga', 'Ada acara penting', dll.",
                             key="keterangan_leave")
    
    # Upload surat dokter jika sakit dengan surat
    medical_letter = None
    if selected_reason == "SICK":
        medical_letter = st.file_uploader("Upload Surat Dokter*", type=["pdf", "jpg", "png", "docx"], key="medical_uploader_leave")
        if medical_letter:
            st.success("✅ Surat dokter telah diupload")
        else:
            st.warning("⚠️ Surat dokter wajib diupload untuk pengajuan sakit")
    
    st.markdown("---")
    
    # TOMBOL SUBMIT
    if st.button("Submit Request", type="primary", key="submit_leave_primary_final"):
        # Validasi dasar
        if end_date < start_date:
            st.error("❌ Tanggal akhir harus setelah tanggal mulai")
            return
        if selected_reason == "SICK" and not medical_letter:
            st.error("❌ Surat dokter wajib diupload untuk sakit dengan surat")
            return
        
        # Validasi saldo
        q = user_quota(user["id"], start_date.year)
        
        if selected_reason == "CHANGEOFF":
            if q['co_balance'] <= 0:
                st.error("❌ Tidak bisa submit Change Off. Saldo Change Off Anda: 0 hari.")
                return
            elif q['co_balance'] < total_days:
                st.error(f"❌ Saldo Change Off tidak cukup. Tersedia {q['co_balance']} hari, diminta {total_days}.")
                return
        elif selected_reason == "PERSONAL":
            if q['leave_balance'] <= 0:
                st.error("❌ Tidak bisa submit Cuti Personal. Saldo cuti Anda: 0 hari.")
                return
            elif q['leave_balance'] < total_days:
                st.error(f"❌ Saldo cuti tidak cukup. Tersedia {q['leave_balance']} hari, diminta {total_days}.")
                return
        
        if not require_manager_assigned(user):
            return
        
        # Simpan data
        try:
            from file_utils import save_file
            medical_path = None
            if selected_reason == "SICK" and medical_letter:
                medical_path = save_file(medical_letter)
            
            now = get_current_local_time().isoformat()
            conn = get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO requests(
                    user_id, type, start_date, end_date, reason, status,
                    created_at, updated_at, file_uploaded, keterangan
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                user["id"],
                'LEAVE',
                start_date.isoformat(),
                end_date.isoformat(),
                selected_reason,
                'PENDING_MANAGER',
                now,
                now,
                1 if medical_path else 0,
                keterangan if keterangan and keterangan.strip() else None
            ))
            conn.commit()
            conn.close()
            
            st.success("✅ Pengajuan cuti/izin berhasil dikirim. Menunggu persetujuan Manager.")
            st.balloons()
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")

def page_submit_changeoff(user):
    """Form pengajuan change off"""
    st.header("Submit Change Off")
    
    # Sidebar untuk history changeoff
    st.sidebar.subheader("History Change Off")
    df_history = get_user_requests_history(user["id"])
    changeoff_history = df_history[df_history["type"] == "CHANGEOFF"] if not df_history.empty else pd.DataFrame()
    
    if not changeoff_history.empty:
        for idx, req in changeoff_history.iterrows():
            status_icon = "✅" if req["status"] == "APPROVED" else "⏳" if "PENDING" in req["status"] else "❌"
            st.sidebar.info(f"{status_icon} CHANGEOFF - {req['status']}\n"
                           f"Tanggal: {format_date_for_display(req.get('departure_date', ''))} to {format_date_for_display(req.get('return_date', ''))}\n"
                           f"Jam: {req.get('hours', 0)} hours")
    else:
        st.sidebar.info("Belum ada history change off")

    col1, col2 = st.columns(2)
    with col1:
        departure_date = st.date_input("Tanggal Keberangkatan*", date.today(), key="departure_date_co")
    with col2:
        return_date = st.date_input("Tanggal Kepulangan*", date.today(), key="return_date_co")

    total_days = (return_date - departure_date).days + 1
    if total_days <= 0:
        st.error("Tanggal kepulangan harus setelah tanggal keberangkatan.")
        return

    st.success(f"✅ Total hari aktivitas: {total_days} hari")

    location = st.text_input("Lokasi*", key="location_co")
    pic = st.text_input("PIC*", key="pic_co")
    job_exec = st.text_input("Job Eksekusi (opsional)", key="job_exec_co")

    # Input keterangan
    st.markdown("---")
    st.subheader("Informasi Tambahan")
    keterangan = st.text_area("Keterangan Change Off (Opsional)",
                             placeholder="Tambahkan keterangan atau catatan tambahan untuk change off ini...",
                             height=100,
                             help="Contoh: 'Client meeting penting', 'Site visit untuk project X', dll.",
                             key="keterangan_co")

    st.subheader("Detail Aktivitas per Hari")
    activities_data = []

    for day in range(total_days):
        current_date = departure_date + timedelta(days=day)
        st.markdown(f"### Hari {day + 1} - {current_date.strftime('%A, %d %B %Y')}")
        
        col3, col4 = st.columns(2)
        with col3:
            start_time = st.time_input(
                f"Waktu Mulai* - Hari {day+1}",
                value=datetime.strptime("08:00", "%H:%M").time(),
                key=f"start_time_{day}"
            )
        with col4:
            end_time = st.time_input(
                f"Waktu Selesai* - Hari {day+1}",
                value=datetime.strptime("17:00", "%H:%M").time(),
                key=f"end_time_{day}"
            )
        
        activity_desc = st.text_area(
            f"Detail Aktivitas* - Hari {day+1}",
            placeholder="Deskripsikan aktivitas yang dilakukan",
            key=f"activity_{day}"
        )
        
        activities_data.append({
            "hari": day + 1,
            "tanggal": current_date.isoformat(),
            "waktu_mulai": start_time.strftime("%H:%M"),
            "waktu_selesai": end_time.strftime("%H:%M"),
            "aktivitas": activity_desc
        })

    if activities_data:
        st.subheader("Preview Aktivitas")
        preview_df = pd.DataFrame(activities_data)
        preview_df['tanggal'] = pd.to_datetime(preview_df['tanggal']).dt.strftime('%A, %Y-%m-%d')
        
        # Tambah kolom perhitungan jam dan eligibility change off
        def calculate_hours_and_eligibility(row):
            try:
                start = datetime.strptime(row['waktu_mulai'], '%H:%M')
                end = datetime.strptime(row['waktu_selesai'], '%H:%M')
                if end < start:
                    end = end.replace(day=end.day + 1)
                hours = (end - start).total_seconds() / 3600
                return hours
            except:
                return 0
        
        preview_df['jam_kerja'] = preview_df.apply(calculate_hours_and_eligibility, axis=1)
        preview_df['dapat_co'] = preview_df['jam_kerja'].apply(lambda x: "✅ Ya" if x > 8 else "❌ Tidak")
        
        st.dataframe(preview_df[['hari', 'tanggal', 'waktu_mulai', 'waktu_selesai', 'jam_kerja', 'dapat_co', 'aktivitas']],
                    use_container_width=True, hide_index=True)
        
        # Tampilkan summary perhitungan
        eligible_days = len(preview_df[preview_df['dapat_co'] == "✅ Ya"])
        total_hours = preview_df['jam_kerja'].sum()
        st.info(f"📊 **Perhitungan Change Off:**\n"
               f"- Hari dengan aktivitas > 8 jam: **{eligible_days} hari**\n"
               f"- Total jam kerja: {total_hours:.1f} jam\n"
               f"- **Change Off yang akan diperoleh: {eligible_days} hari** (aturan baru)\n"
               f"- Perhitungan lama: {int(total_hours/8)} hari ({total_hours:.1f} jam ÷ 8)")

    file = st.file_uploader("Upload Timesheet*", type=["pdf", "jpg", "png", "docx", "xlsx"], key="timesheet_co")
    if file:
        st.success("✅ File telah diupload")

    if st.button("Submit Change Off", type="primary", key="submit_co_btn"):
        if not require_manager_assigned(user):
            return
        
        if not file:
            st.error("Timesheet wajib diupload.")
            return
        elif not location or not pic:
            st.error("Harap isi Lokasi dan PIC.")
            return
        elif departure_date > return_date:
            st.error("Tanggal kepulangan harus setelah tanggal keberangkatan.")
            return

        try:
            from file_utils import save_file
            path = save_file(file)
            activities_json = json.dumps(activities_data, ensure_ascii=False)
            
            # PERBAIKAN: Hitung change off berdasarkan aturan baru
            total_hours = 0
            change_off_days = 0
            
            for activity in activities_data:
                start_str = activity['waktu_mulai']
                end_str = activity['waktu_selesai']
                start_dt = datetime.strptime(start_str, '%H:%M')
                end_dt = datetime.strptime(end_str, '%H:%M')
                if end_dt < start_dt:
                    end_dt = end_dt.replace(day=end_dt.day + 1)
                
                daily_hours = (end_dt - start_dt).total_seconds() / 3600
                total_hours += daily_hours
                
                # ATURAN BARU: Jika aktivitas harian > 8 jam = dapat 1 hari change off
                if daily_hours > 8:
                    change_off_days += 1

            now = get_current_local_time().isoformat()
            conn = get_conn()
            cur = conn.cursor()
            
            # PERBAIKAN: Query INSERT yang benar dengan semua kolom
            cur.execute("""
                INSERT INTO requests(
                    user_id, type, start_date, end_date, departure_date, return_date, 
                    hours, change_off_days, reason, status, timesheet_path, location, pic, 
                    activities_json, created_at, updated_at, file_uploaded, keterangan
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                user["id"], 
                'CHANGEOFF', 
                departure_date.isoformat(),      # start_date = departure_date
                return_date.isoformat(),         # end_date = return_date
                departure_date.isoformat(),      # departure_date
                return_date.isoformat(),         # return_date
                total_hours,                     # hours
                change_off_days,                 # change_off_days (NEW)
                'CHANGEOFF',                     # reason
                'PENDING_MANAGER',               # status
                path,                           # timesheet_path
                location,                       # location
                pic,                            # pic
                activities_json,                # activities_json
                now,                            # created_at
                now,                            # updated_at
                1,                              # file_uploaded
                keterangan if keterangan and keterangan.strip() else None  # keterangan
            ))
            conn.commit()
            conn.close()
            
            st.success(f"✅ Change Off request terkirim! Anda akan mendapat **{change_off_days} hari** change off jika disetujui.")
            st.balloons()
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            # Debug info
            st.error(f"Debug info: Total columns expected vs provided")


def page_my_requests(user):
    """Halaman history requests karyawan"""
    st.header("My Requests History")
    
    # Dapatkan data requests
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT r.*, u.name as employee_name, m.email as manager_email, m.name as manager_name
        FROM requests r
        JOIN users u ON r.user_id = u.id
        LEFT JOIN users m ON u.manager_id = m.id
        WHERE r.user_id=?
        ORDER BY r.created_at DESC
    """, conn, params=(user["id"],))
    conn.close()
    
    if df.empty:
        st.info("Belum ada request.")
        return

    # Filter options
    filter_type = st.selectbox("Filter by Type", ["ALL", "LEAVE", "CHANGEOFF"], key="filter_type_select")
    filter_status = st.selectbox("Filter by Status", ["ALL", "PENDING", "APPROVED", "REJECTED"], key="filter_status_select")

    # Apply filters
    if filter_type != "ALL":
        df = df[df["type"] == filter_type]
    if filter_status != "ALL":
        df = df[df["status"].str.contains(filter_status, case=False)]

    # Display requests
    for idx, r in df.iterrows():
        status_icon = "✅" if r["status"] == "APPROVED" else "⏳" if "PENDING" in r["status"] else "❌"
        with st.expander(f"{status_icon} {r['type']} - {r['status']} - ID: {r['id']}", expanded=False):
            
            request_data = {
                "Request ID": str(r["id"]),
                "Type": str(r["type"]),
                "Status": str(r["status"]),
                "Created At (WIB)": convert_to_local_time(r["created_at"]),
                "Updated At (WIB)": convert_to_local_time(r["updated_at"])
            }
            
            if r["type"] == "LEAVE":
                request_data.update({
                    "Start Date": format_date_for_display(r.get("start_date", "")),
                    "End Date": format_date_for_display(r.get("end_date", "")),
                    "Reason": str(r.get("reason", "")),
                    "Employee Name": str(r.get("employee_name", "")),
                    "Keterangan": str(r.get("keterangan", "-"))
                })
            else:  # CHANGEOFF
                # Gunakan departure_date/return_date jika ada, fallback ke start_date/end_date
                departure = r.get("departure_date") or r.get("start_date", "")
                return_d = r.get("return_date") or r.get("end_date", "")
                
                request_data.update({
                    "Departure Date": format_date_for_display(departure),
                    "Return Date": format_date_for_display(return_d),
                    "Total Hours": str(r.get("hours", 0)),
                    "Location": str(r.get("location", "")),
                    "PIC": str(r.get("pic", "")),
                    "Keterangan": str(r.get("keterangan", "-"))
                })

            # Tampilkan sebagai dataframe
            st.dataframe(pd.DataFrame.from_dict(request_data, orient='index', columns=['Value']),
                        use_container_width=True)

            # Email reminder untuk pending requests
            if r["status"] in ["PENDING_MANAGER", "PENDING_HR"] and r.get("manager_email"):
                st.markdown("---")
                st.subheader("📧 Kirim Email Reminder")
                
                keterangan_text = f"Additional Notes: {r.get('keterangan', '')}" if r.get('keterangan') else ""
                
                # Generate email content
                if r["type"] == "LEAVE":
                    subject = f"Reminder: Leave Request Approval - {r['employee_name']} - {r.get('start_date', '')} to {r.get('end_date', '')}"
                    body = f"""Dear {r.get('manager_name', 'Manager')} and HR Team,

I would like to kindly follow up on my leave request from {format_date_for_display(r.get('start_date', ''))} to {format_date_for_display(r.get('end_date', ''))} due to {r.get('reason', '')}.

Request ID: {r['id']}
Status: {r['status']}
{keterangan_text}

Thank you for your consideration.

Best regards,
{r['employee_name']}"""
                else:  # CHANGEOFF
                    departure = r.get("departure_date") or r.get("start_date", "")
                    return_d = r.get("return_date") or r.get("end_date", "")
                    
                    subject = f"Reminder: Change Off Request Approval - {r['employee_name']} - {departure} to {return_d}"
                    body = f"""Dear {r.get('manager_name', 'Manager')} and HR Team,

I would like to kindly follow up on my change off request from {format_date_for_display(departure)} to {format_date_for_display(return_d)}.

Request ID: {r['id']}
Location: {r.get('location', '')}
PIC: {r.get('pic', '')}
Status: {r['status']}
{keterangan_text}

Thank you for your consideration.

Best regards,
{r['employee_name']}"""

                # Encode untuk URL
                import urllib.parse
                subject_encoded = urllib.parse.quote(subject)
                body_encoded = urllib.parse.quote(body)
                
                # Buat Outlook URL
                outlook_url = f"mailto:{r['manager_email']}?subject={subject_encoded}&body={body_encoded}"
                
                # Tombol buka Outlook
                if st.button(f"📧 Kirim Email ke Manager", key=f"email_btn_{r['id']}_{idx}"):
                    st.markdown(f"""
**Email akan dibuka di Outlook:**
- **To:** {r['manager_email']}
- **Subject:** {subject}
                    """)
                    
                    st.markdown(f'<a href="{outlook_url}" target="_blank"><button style="background-color: #0078D4; color: white; padding: 10px 20px; border: none; border-radius: 5px;">Buka di Outlook</button></a>',
                               unsafe_allow_html=True)
                    st.info("✅ Email template sudah siap. Klik 'Buka di Outlook' untuk membuka aplikasi email Anda.")

            # Tampilkan file jika ada
            if r.get('file_uploaded', 0) and r.get('timesheet_path'):
                st.info("Attached File:")
                preview_file(r['timesheet_path'], key_prefix=f"req_{r['id']}", user_role=user["role"])