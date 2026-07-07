# Use official Python base image with slim Debian Bullseye
FROM python:3.10-slim-bullseye

# Metadata
LABEL maintainer="daniel"

# Avoid prompts during install
ENV DEBIAN_FRONTEND=noninteractive


# Prepare Microsoft keyring and repo (Bullseye)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    chmod 644 /etc/apt/keyrings/microsoft.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/11/prod bullseye main" > /etc/apt/sources.list.d/mssql-release.list

# Set working directory
WORKDIR /app

# Step 3: Install system dependencies including LibreOffice and ODBC support
RUN apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    unixodbc \
    unixodbc-dev \
    msodbcsql18 \
    libsqlite3-dev \
    libsasl2-dev \
    libldap2-dev \
    libssl-dev \
    libffi-dev \
    libreoffice \
    libreoffice-writer \
    libgdk-pixbuf-2.0-0 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Step 4: Copy requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 5: Copy the rest of the application code
COPY . .

# Step 6: Create uploads directory for serving documents
RUN mkdir -p /app/uploads

# Step 7: Expose FastAPI app port (ignored by Cloud Run, but good for local/documentative purposes)
EXPOSE 8000

# Step 8: Start FastAPI app using Uvicorn, respecting the PORT env var for Cloud Run
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]