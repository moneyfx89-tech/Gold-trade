FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-thai-tlwg fonts-lao \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
ENV DB_PATH=/data/records.db PORT=8080
VOLUME /data
EXPOSE 8080
CMD ["python", "bot.py"]
