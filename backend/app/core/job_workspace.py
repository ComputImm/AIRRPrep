from pathlib import Path

from app.config import JOBS_DIR
from app.core.security import is_safe_identifier


class JobWorkspace:

    def __init__(self, session_id, job_id):
        session_id = str(session_id)
        job_id = str(job_id)

        # session_id/job_id become filesystem path segments below — refuse
        # anything that isn't a plain uuid-like token (blocks "../" etc.).
        if not is_safe_identifier(session_id) or not is_safe_identifier(job_id):
            raise ValueError("Invalid session_id or job_id")

        self.job_id = job_id
        self.base_path = JOBS_DIR / session_id / self.job_id

        self.upload_dir = self.base_path / "input"

        self.steps_path = self.base_path / "steps"

        self.outputs_path = self.base_path / "outputs"

    def get_all_files(self):

        result = []

        sections = {
            "input": self.upload_dir,
            "steps": self.steps_path,
            "outputs": self.outputs_path
        }

        for section_name, section_path in sections.items():

            if not section_path.exists():
                continue

            for file in section_path.rglob("*"):

                if file.is_file():

                    result.append({
                        "section": section_name,
                        "name": file.name,
                        "relative_path": str(
                            file.relative_to(self.base_path)
                        ),
                        "size": file.stat().st_size
                    })

        return result

    def create(self):

        self.upload_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.steps_path.mkdir(
            parents=True,
            exist_ok=True
        )

        self.outputs_path.mkdir(
            parents=True,
            exist_ok=True
        )