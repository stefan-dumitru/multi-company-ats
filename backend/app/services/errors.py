class NotFoundError(Exception):
    """The row does not exist, or exists but the caller may not see it.

    Deliberately one error for both (CLAUDE.md): "forbidden" would confirm that an id exists in
    another company.
    """


class RuleViolation(Exception):
    """A business rule says no. One shape for all of them, so the frontend can react to `code`
    and show `message`: the handler in error_handlers.py turns any subclass into a JSON answer."""

    status_code = 409
    code = "rule_violation"
    message = "This change is not allowed."


class VersionConflict(RuleViolation):
    code = "version_conflict"
    message = "This job was changed by someone else. Reload it and try again."


class JobClosed(RuleViolation):
    code = "job_closed"
    message = "A closed job cannot be changed."


class DraftCannotClose(RuleViolation):
    code = "draft_cannot_close"
    message = "A draft cannot be closed. Publish it first, or delete it."


class NoRecruiter(RuleViolation):
    code = "no_recruiter"
    message = "Assign at least one active recruiter before publishing."


class LastRecruiterError(RuleViolation):
    code = "last_recruiter"
    message = "An open job must keep at least one active recruiter."


class OnlyDraftsDeletable(RuleViolation):
    code = "only_drafts_deletable"
    message = "Only a draft can be deleted. Close the job instead."


class DepartmentInUse(RuleViolation):
    code = "department_in_use"
    message = "This department is used by jobs. Archive it instead."


class InvalidDepartment(RuleViolation):
    # The same answer for another company's department and for one that does not exist.
    status_code = 422
    code = "department_invalid"
    message = "Choose one of your company's departments."


class ArchivedDepartment(RuleViolation):
    status_code = 422
    code = "department_archived"
    message = "That department is archived. Choose another."


class InvalidRecruiter(RuleViolation):
    # Same answer for a foreign, unknown, deactivated or non-recruiter user.
    status_code = 422
    code = "invalid_recruiter"
    message = "Choose an active recruiter of your company."


class DuplicateDepartmentName(Exception):
    """The company already has a department with this name (ignoring case)."""


class EmailAlreadyRegistered(Exception):
    """An account with this email exists (one email is one account, across all companies)."""


class InvalidInvitation(Exception):
    """The invitation link is unknown, used, revoked or expired. Callers give one answer for all."""


class LastAdminError(Exception):
    """The change would leave a company without an active admin (data-model.md > Company)."""


class ResendLimitReached(Exception):
    """Too many verification emails requested for this account within the last hour."""


class EmailNotVerified(Exception):
    """The caller is logged in but has not verified their email, so may only use their account."""
