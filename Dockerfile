FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Create necessary directories
RUN mkdir -p uploads data

# Set environment variables
ENV PYTHONPATH=/app
ENV STREAMLIT_SERVER_PORT=8577
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV HRMS_UPLOAD_DIR=/app/uploads

# Expose Streamlit port
EXPOSE 8577

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:8577/_stcore/health || exit 1

# Run the application
CMD ["streamlit", "run", "main.py", "--server.port=8577", "--server.address=0.0.0.0"]
