from app.core.job_store import get_job, update_job

session_id = "d00ee47d-3f44-4084-b29f-ca504ad9443b"
job_id = "3469a539-53db-4906-9de6-706bca7033e1"

job = get_job(session_id, job_id)

step14 = {
    "index": 2,
    "name": "ParseHeaders.table",
    "lanes": ["R1"],
    "before": 0,
    "failed": 0,
    "remaining": 0,
    "by_lane": {
        "R1": {
            "before": 0,
            "failed": 0,
            "remaining": 0
        }
    },
    "output_paths": {
        "R1": r""
    }
}
step_stats = job["step_stats"]
step_stats.append(step14)

update_job(
    session_id,
    job_id,
    {
        "status": (
            "DONE ParseHeaders.table "
            "STEP 14 OF 14 | "
            "before=2419 "
            "failed=0 "
            "remaining=2419"
        ),
        "stream": {
            "mode": "single",
            "r1": r"C:\Users\sahar\OneDrive\Desktop\shayesteh\Preprocessing\presto-backend\jobs\d00ee47d-3f44-4084-b29f-ca504ad9443b\ffbe8415-2c34-425c-bfb7-998b57682acd\outputs\final.tsv"
        },
        "step_stats": step_stats,
        "last_step_stats": step14,
    }
)