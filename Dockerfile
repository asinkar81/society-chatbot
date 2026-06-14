# Use Python slim base image to minimize size (fits in Artifact Registry 500MB free limit)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose default port
EXPOSE 8080

# Command to run Streamlit, dynamically using the PORT environment variable passed by Cloud Run
CMD ["sh", "-c", "streamlit run main.py --server.port=${PORT:-8080} --server.address=0.0.0.0"]
