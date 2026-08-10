FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SERVICE_DESK_DB=/data/service-desk.db
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser && mkdir /data && chown appuser:appuser /data
COPY pyproject.toml ./
COPY service_desk ./service_desk
COPY static ./static
RUN pip install --no-cache-dir .
USER 10001
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn","service_desk.app:app","--host","0.0.0.0","--port","8000"]
