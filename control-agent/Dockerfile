FROM docker:29.6.1-cli

RUN apk add --no-cache python3

WORKDIR /app
COPY server.py ./server.py

EXPOSE 8770
CMD ["python3", "/app/server.py"]
