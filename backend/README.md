# Preprocessing Backend

## Prerequisites

Before running the project, make sure the following software is installed:

- Python 3.12 or newer
- Redis
- PostgreSQL (if required by the project)
- Git (optional)

---

## Clone the Repository

Using SSH:

```bash
git clone git@github.com:fatemeh21ch/preprocessing_backend.git
```

Or using HTTPS:

```bash
git clone https://github.com/fatemeh21ch/preprocessing_backend.git
```

Move into the project directory:

```bash
cd preprocessing_backend
```

---

## Create a Virtual Environment

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## Install Dependencies

Install all required Python packages:

```bash
pip install -r requirements.txt
```

---

## Configure Environment Variables

If the project uses environment variables, create and configure the `.env` file before starting the application.

---

## Start Required Services

Before running the backend, make sure the required services are running:

- Redis

---

## Start the Backend

The backend requires **two separate terminals**.

### Terminal 1 – Start FastAPI

```bash
uvicorn main:app --reload
```

### Terminal 2 – Start Celery Worker

```bash
python -m celery -A app.workers.celery_worker worker --pool=solo --loglevel=info
```

---

## API Documentation

After the backend starts successfully, the API will be available at:

### Base URL

```
http://127.0.0.1:8000
```

### Swagger UI

```
http://127.0.0.1:8000/docs
```

### ReDoc

```
http://127.0.0.1:8000/redoc
```

---

## Project Structure

```text
preprocessing_backend/
│
├── app/
│   ├── workers/
│   │   └── celery_worker.py
│   └── ...
│
├── main.py
├── requirements.txt
└── README.md
```

---

## Notes

- Always activate the virtual environment before running the project.
- Install dependencies using:

  ```bash
  pip install -r requirements.txt
  ```

- Ensure Redis is running before starting the Celery worker.
- Both the FastAPI server and the Celery worker must be running for the application to function correctly.
