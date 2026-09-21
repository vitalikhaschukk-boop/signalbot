FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/mpl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# бот ходить у Telegram сам (long polling) — вхідних портів не треба
CMD ["python", "bot/main.py"]
