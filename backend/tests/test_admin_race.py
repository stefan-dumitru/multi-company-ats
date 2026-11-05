"""Two admins deactivating each other at the same moment must not empty the company of admins.

This needs two real database sessions, so it cannot use the shared `db` fixture session for the
actors: it commits its setup, then each side works in its own session and transaction.
"""

import threading
import time
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import Role, User
from app.services.errors import LastAdminError
from app.services.users import deactivate_user
from tests.factories import make_company, make_user


def test_simultaneous_deactivations_leave_one_admin(db: Session, scratch_engine: Engine) -> None:
    company = make_company(db)
    ada = make_user(db, email="ada@acme.test", role=Role.COMPANY_ADMIN, company=company)
    bob = make_user(db, email="bob@acme.test", role=Role.COMPANY_ADMIN, company=company)
    db.commit()
    ada_id, bob_id = ada.id, bob.id
    outcome: dict[str, object] = {}

    first = Session(scratch_engine)
    second = Session(scratch_engine)
    try:
        # Ada deactivates Bob, but has not committed yet: her transaction holds the company lock.
        ada_in_first = first.get(User, ada_id)
        assert ada_in_first is not None
        deactivate_user(first, ada_in_first, bob_id, datetime.now(UTC))

        def bob_deactivates_ada() -> None:
            bob_in_second = second.get(User, bob_id)
            assert bob_in_second is not None
            try:
                deactivate_user(second, bob_in_second, ada_id, datetime.now(UTC))
                second.commit()
                outcome["result"] = "deactivated"
            except LastAdminError:
                second.rollback()
                outcome["result"] = "refused"

        thread = threading.Thread(target=bob_deactivates_ada)
        thread.start()
        time.sleep(1.0)
        # Bob's request must be waiting for the lock, not racing ahead on stale information.
        assert thread.is_alive(), "the second deactivation did not wait for the company lock"

        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    assert outcome["result"] == "refused"
    with Session(scratch_engine) as check:
        active_admins = check.scalars(
            select(User).where(User.company_id == company.id, User.is_active.is_(True))
        ).all()
    assert [admin.email for admin in active_admins] == ["ada@acme.test"]
