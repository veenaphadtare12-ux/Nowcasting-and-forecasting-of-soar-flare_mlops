# flare-api: FastAPI service + Prefect flows, models and replay data from the committed model bundle.
FROM python:3.12-slim

ARG GIT_SHA=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLARE_GIT_SHA=${GIT_SHA} \
    FLARE_BUNDLE_DIR=/app/model_bundle \
    FLARE_PREDICTIONS_DIR=/data/predictions \
    FLARE_DRIFT_FILE=/data/drift/latest.json \
    PREFECT_HOME=/data/prefect \
    MLFLOW_DISABLE_AGENT_HINT=1

WORKDIR /app
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data/predictions /data/drift /data/prefect \
 && chown -R app:app /data

COPY requirements-serve.txt requirements-worker.txt ./
RUN pip install -r requirements-serve.txt -r requirements-worker.txt

COPY params.yaml ./
COPY src/ src/
COPY flows/ flows/
COPY model_bundle/ model_bundle/

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
LABEL org.opencontainers.image.source="https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.title="flare-api"
CMD ["uvicorn", "src.serving.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
