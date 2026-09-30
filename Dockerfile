FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RAG_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY .streamlit ./.streamlit
RUN pip install --upgrade pip && pip install .

# Run as an unprivileged user; knowledge bases live on a mounted volume
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]

EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# Default: REST API. For the web UI:  docker run ... rag-generator ui
CMD ["uvicorn", "rag_generator.api:app", "--host", "0.0.0.0", "--port", "8000"]
