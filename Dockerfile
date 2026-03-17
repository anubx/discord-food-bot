FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for pyzbar (barcode scanning)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "bot.py"]
