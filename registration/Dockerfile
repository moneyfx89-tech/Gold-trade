FROM python:3.12-slim
WORKDIR /app
COPY server.py config.json ./
COPY static ./static
ENV REG_DB_PATH=/data/registrations.db REG_PORT=8090
VOLUME /data
EXPOSE 8090
CMD ["python", "server.py"]
