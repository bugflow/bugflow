"""The tenant a program serves, and the other tenants the ingress
reaches, are read from their settings (ADR 011)."""

import pytest

from bugflow.apps.shared.tenancy import Tenant, tenant_from, tenants_from


def test_a_server_that_names_no_tenant_is_the_default() -> None:
    assert tenant_from({}) == "default"
    assert tenant_from({"TENANT": ""}) == "default"
    assert tenant_from({"TENANT": " brand "}) == ("brand")


def test_a_name_that_is_no_tenants_stops_the_program() -> None:
    with pytest.raises(ValueError, match="TENANT is 'Brand Team'"):
        tenant_from({"TENANT": "Brand Team"})


def test_the_other_tenants_say_where_each_workers_queue_is() -> None:
    assert tenants_from({}) == ()
    assert tenants_from(
        {"TENANTS": "brand=brand/br, operations=operations/ops,"}
    ) == (
        Tenant(
            name="brand",
            namespace="brand",
            task_queue="br",
        ),
        Tenant(
            name="operations",
            namespace="operations",
            task_queue="ops",
        ),
    )


@pytest.mark.parametrize(
    ("listed", "reason"),
    [
        ("brand", "tenant=namespace/task-queue"),
        ("brand=br", "tenant=namespace/task-queue"),
        ("=br/queue", "tenant=namespace/task-queue"),
        ("Brand=br/queue", "no tenant's name"),
        ("default=default/queue", "own tenant"),
        ("br=br/q,br=br/q", "twice"),
    ],
)
def test_an_entry_that_is_not_a_tenant_stops_the_ingress(
    listed: str, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        tenants_from({"TENANTS": listed})
