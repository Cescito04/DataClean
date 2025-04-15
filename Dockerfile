FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip config set global.index-url https://pypi.org/simple/ && \
    pip config set global.timeout 180 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

RUN echo "from app import db; db.create_all()" > init_db.py

CMD sh -c "python init_db.py && flask run --host=0.0.0.0 --port=5000"