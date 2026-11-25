# FinGuard AI application image (API + web UI). PostgreSQL runs as a separate compose service.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# CPU-only PyTorch first (the default Linux wheel bundles CUDA and is ~2 GB larger), then the rest.
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

# Bake the embedding model into the image so the container never needs the internet at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
 && chmod -R a+rX /opt/hf
ENV HF_HUB_OFFLINE=1

COPY . .

# Run as a non-root user. These folders become named volumes (see docker-compose.yml).
RUN useradd --create-home --uid 1000 finguard \
 && mkdir -p data/raw data/chroma models docs/reports \
 && chown -R finguard:finguard /app
USER finguard

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"

CMD ["uvicorn", "main:app", "--app-dir", "src/api", "--host", "0.0.0.0", "--port", "8000"]

