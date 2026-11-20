from infrasales.audit.models import AuditEvent
from infrasales.audit.schemas import AuditEventRead


def test_admins_do_not_see_client_networks() -> None:
    audit_event = AuditEvent(
        actor="basic:alice", action="auth.login", client_network="203.0.113.0/24"
    )

    read = AuditEventRead.model_validate(audit_event, from_attributes=True)

    assert read.actor == "basic:alice"
    assert "client_network" not in read.model_dump()
