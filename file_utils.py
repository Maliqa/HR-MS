import os
import uuid
import base64
import mimetypes
import streamlit as st
from datetime import datetime

UPLOAD_DIR = os.environ.get("HRMS_UPLOAD_DIR", "uploads")

def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"

def save_file(uploaded_file) -> str:
    """Simpan file upload ke server dan return path"""
    ext = os.path.splitext(uploaded_file.name)[1]
    fname = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex}{ext}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path

def preview_pdf_iframe(file_path, width="100%", height=900):
    try:
        with open(file_path, "rb") as f:
            base64_pdf = base64.b64encode(f.read()).decode('utf-8')
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="{width}" height="{height}" type="application/pdf" style="border: none;"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Gagal menampilkan PDF: {e}")

def preview_file(path: str, label_prefix: str = "Attachment", key_prefix: str = None, user_role: str = "EMPLOYEE"):
    if not os.path.exists(path):
        st.error("File tidak ditemukan di server.")
        return
    if key_prefix is None:
        key_prefix = os.path.basename(path)
    size = os.path.getsize(path)
    mime, _ = mimetypes.guess_type(path)
    ext = (os.path.splitext(path)[1] or "").lower()
    st.write(f"{label_prefix}: {os.path.basename(path)} • {human_size(size)} • {mime or 'application/octet-stream'}")
    with open(path, "rb") as f:
        st.download_button("Download File", f, file_name=os.path.basename(path), mime=mime or "application/octet-stream", key=f"dl_{key_prefix}")
    if user_role not in ["MANAGER", "HR_ADMIN"]:
        st.info("Hanya Manager dan HR yang dapat melihat preview file.")
        return
    if ext == ".pdf" or (mime == "application/pdf"):
        preview_pdf_iframe(path, width="100%", height=900)
    else:
        st.warning("Preview hanya tersedia untuk file PDF. Tipe lain hanya dapat diunduh.")