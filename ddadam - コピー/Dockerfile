# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Expose (optional)
EXPOSE 3000

# Use Vercel-provided PORT if available
ENV PORT=3000

# Run Streamlit bound to the correct interface and port
CMD ["bash", "-lc", "streamlit run player_verification_system_v2.py --server.address=0.0.0.0 --server.port=${PORT}"]
