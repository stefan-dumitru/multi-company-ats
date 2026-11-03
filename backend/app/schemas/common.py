from typing import Annotated

from pydantic import StringConstraints

# Deliberately simple: one "@", no spaces, a dot in the domain. Real proof that an address works
# is the verification email (Phase 3); a stricter pattern only rejects unusual-but-valid ones.
EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]

PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
