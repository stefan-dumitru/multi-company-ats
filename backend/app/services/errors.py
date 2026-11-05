class NotFoundError(Exception):
    """The row does not exist, or exists but the caller may not see it.

    Deliberately one error for both (CLAUDE.md): "forbidden" would confirm that an id exists in
    another company.
    """


class EmailAlreadyRegistered(Exception):
    """An account with this email exists (one email is one account, across all companies)."""


class InvalidInvitation(Exception):
    """The invitation link is unknown, used, revoked or expired. Callers give one answer for all."""


class LastAdminError(Exception):
    """The change would leave a company without an active admin (data-model.md > Company)."""
