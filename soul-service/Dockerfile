FROM node:22.22-alpine AS dashboard-build

WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY soul-service/pyproject.toml soul-service/README.md ./
COPY soul-service/src ./src
COPY soul-service/assets ./assets
COPY addons /app/addons
COPY --from=dashboard-build /dashboard/dist /app/dashboard
RUN pip install --no-cache-dir .
RUN mkdir /data && chown 65532:65532 /data

USER 65532:65532
EXPOSE 8765

CMD ["python3", "-m", "soulforge.server"]
