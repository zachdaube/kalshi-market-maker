FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ src/
COPY config/ config/
COPY run_market_maker.py .
COPY dashboard.py .
COPY trading_worker.py .

# Expose dashboard port
EXPOSE 8080

# Default: run dashboard (includes bot)
CMD ["python", "dashboard.py", "--env", "demo", "--port", "8080"]
