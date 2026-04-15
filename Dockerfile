FROM python:3.11-slim

# System deps for PyMuPDF and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    g++ \
    libmupdf-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model so workers don't fetch it at runtime
# The model is cached in the HuggingFace cache dir
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# Shared data volumes (uploads + FAISS indices)
RUN mkdir -p /data/uploads /data/indices

EXPOSE 8000
