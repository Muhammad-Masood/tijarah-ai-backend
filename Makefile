run: 
	poetry run uvicorn neurocom_backend.main:app --host 192.168.0.108 --port 8000 --reload