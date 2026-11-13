"""Every model is imported here so `Base.metadata` knows all tables (Alembic relies on it)."""

from app.models.audit_log import AuditLog
from app.models.background_job import BackgroundJob, JobStatus
from app.models.candidate_profile import CandidateProfile
from app.models.company import Company
from app.models.department import Department
from app.models.file import File
from app.models.invitation import Invitation
from app.models.job import Job, JobRecruiter, PostingStatus
from app.models.login_attempt import LoginAttempt
from app.models.session import UserSession
from app.models.user import STAFF_ROLES, Role, User
from app.models.user_token import UserToken
from app.models.worker_heartbeat import WorkerHeartbeat

__all__ = [
    "STAFF_ROLES",
    "AuditLog",
    "BackgroundJob",
    "CandidateProfile",
    "Company",
    "Department",
    "File",
    "Invitation",
    "Job",
    "JobRecruiter",
    "JobStatus",
    "LoginAttempt",
    "PostingStatus",
    "Role",
    "User",
    "UserSession",
    "UserToken",
    "WorkerHeartbeat",
]
