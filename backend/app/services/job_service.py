
import uuid
from datetime import datetime
from app.core.job_store import create_job as save_job

import uuid
from datetime import datetime

from app.core.job_store import create_job as save_job


def create_job(
    file_path,
    session_id,
    steps ,
):
    job_id = str(uuid.uuid4())
    serilized_steps = [step.model_dump() for step in steps]
    print(serilized_steps)
    job_data = {
        "job_id": job_id,
        "session_id": session_id,
        "file_path": file_path,
        "steps": serilized_steps,
        "status": "PENDING",
        "created_at": str(datetime.now()),
        "result": None,
        "error": None,
    }

    save_job(
        session_id=session_id,
        job_id=job_id,
        data=job_data
    )

    return job_id

