class NotFoundError(Exception):
    """The row does not exist, or exists but the caller may not see it.

    Deliberately one error for both (CLAUDE.md): "forbidden" would confirm that an id exists in
    another company.
    """
