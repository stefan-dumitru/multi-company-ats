# One image serves both the API and the built React app (same origin, so no CORS).
# The same image is deployed to staging and production; only configuration differs.

# --- Stage 1: build the frontend. Nothing from this stage except dist/ reaches the final image.
FROM node:26-slim AS frontend-build
WORKDIR /frontend
# Dependency files first, so the (slow) install is cached until they change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: the runtime image.
FROM python:3.14-slim AS runtime
# No .pyc files, and logs go straight to stdout instead of being buffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
# pip is removed afterwards: the app never needs it at runtime, its bundled libraries were the only
# vulnerabilities Trivy found, and a compromised container can no longer install more software.
RUN pip install --no-cache-dir -r requirements.txt && pip uninstall -y pip

COPY backend/app ./app
# Migrations ship in the image so the deploy pipeline can run `alembic upgrade head` with it.
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY --from=frontend-build /frontend/dist ./static
ENV STATIC_DIR=/app/static

# Run as an unprivileged user: a compromised app should not own the container.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8000
# Hosting platforms such as Railway tell the container which port to use through $PORT; locally it
# defaults to 8000. Python, not curl, because the slim image has no curl.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=8)"]

# Shell form so ${PORT:-8000} is expanded; `exec` makes uvicorn the main process, so it receives the
# stop signal and shuts down cleanly instead of being killed after a timeout.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
