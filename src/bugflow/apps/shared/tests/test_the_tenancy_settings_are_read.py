"""The tenant a program serves, and the other tenants the ingress
reaches, are read from their settings (ADR 011)."""

import pytest

from bugflow.apps.shared.tenancy import Tenant, tenant_from, tenants_from


def test_a_server_that_names_no_tenant_is_the_default() -> None:
    assert tenant_from({}) == "default"
    assert tenant_from({"TENANT": ""}) == "default"
    assert tenant_from({"TENANT": " business-development "}) == (
        "business-development"
    )


def test_a_name_that_is_no_tenants_stops_the_program() -> None:
    with pytest.raises(ValueError, match="TENANT is 'Business Dev'"):
        tenant_from({"TENANT": "Business Dev"})


def test_the_other_tenants_say_where_each_workers_queue_is() -> None:
    assert tenants_from({}) == ()
    assert tenants_from(
        {
            "TENANTS": "business-development=business-development/bd, "
            "delivery-assurance=delivery-assurance/da,"
        }
    ) == (
        Tenant(
            name="business-development",
            namespace="business-development",
            task_queue="bd",
        ),
        Tenant(
            name="delivery-assurance",
            namespace="delivery-assurance",
            task_queue="da",
        ),
    )


@pytest.mark.parametrize(
    ("listed", "reason"),
    [
        ("business-development", "tenant=namespace/task-queue"),
        ("business-development=bd", "tenant=namespace/task-queue"),
        ("=bd/queue", "tenant=namespace/task-queue"),
        ("Business=bd/queue", "no tenant's name"),
        ("default=default/queue", "own tenant"),
        ("bd=bd/q,bd=bd/q", "twice"),
    ],
)
def test_an_entry_that_is_not_a_tenant_stops_the_ingress(
    listed: str, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        tenants_from({"TENANTS": listed})
