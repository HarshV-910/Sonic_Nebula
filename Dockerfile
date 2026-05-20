# Use a smaller Python base image to reduce final image size.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
     PYTHONUNBUFFERED=1 \
     PIP_NO_CACHE_DIR=1 \
     STREAMLIT_SERVER_HEADLESS=true

# Set working directory inside the container
WORKDIR /app/

# Copy requirements and install dependencies in one layer.
COPY requirements.txt .
RUN pip install --upgrade pip && \
     pip install --default-timeout=300 -r requirements.txt

COPY ./data/processed/interaction_matrix.npz ./data/processed/
COPY ./data/processed/Music_Info_app.csv ./data/processed/
COPY ./data/processed/Music_Info_flask.csv ./data/processed/
COPY ./data/processed/df_transformed.npz ./data/processed/

COPY ./models/track_ids.npy ./models/

# COPY ./data/raw/Music_Info.csv ./data/raw/

COPY flask/ /app/flask/
COPY ./src/ /app/src/

EXPOSE 8000

CMD ["gunicorn", "--chdir", "flask", "--preload", "--workers", "2", "--threads", "4", "--bind", "0.0.0.0:8000", "app:app"]


# file structure will looks like:
# /app
# │
# ├── requirements.txt
# ├── app.py
# │
# ├── src/
# │   ├── ... (your full source code)
# │
# ├── data/
# │   ├── raw/
# │   │   └── Music_Info.csv
# │   │
# │   └── processed/
# │       ├── interaction_matrix.npz
# │       ├── Music_Info_app.csv
# │       └── df_transformed.npz
# │
# ├── models/
# │   └── track_ids.npy
# │
# └── (Python packages installed globally)