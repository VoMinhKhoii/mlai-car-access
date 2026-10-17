# Ngõ Ngách: one persistent uvicorn process that serves the API and the built frontend from the same origin
# (see README "Deploying" and docs/decision-log.md). Used by render.yaml.

FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8787
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /app/frontend/dist frontend/dist
EXPOSE 8787
# Render terminates TLS at its proxy and is the only way in, so its X-Forwarded-* headers are trusted here;
# that keeps the operator cookie Secure on https.
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
