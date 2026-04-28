FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN mkdir -p /app/replay_tool/static && npm run build

FROM python:3.13-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
COPY --from=frontend /app/replay_tool/static ./replay_tool/static
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn replay_tool.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
