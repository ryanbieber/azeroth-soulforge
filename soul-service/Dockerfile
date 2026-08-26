FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN mkdir /data && chown 65532:65532 /data

USER 65532:65532
EXPOSE 8765

CMD ["python3", "-m", "soulforge.server"]
