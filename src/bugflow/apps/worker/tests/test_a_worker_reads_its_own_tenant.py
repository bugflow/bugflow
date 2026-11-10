"""A worker reviews by its own tenant's deployment in force and reads
its own tenant's settings, and no other tenant's (ADR 011, ADR 012).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime

from bugflow.apps.shared.deploying import deploying_over
from bugflow.apps.shared.policies import reviewers_in_force
from bugflow.apps.worker.review import (
    own_settings,
    parts_from_environment,
    watched_in,
)
from bugflow.apps.worker.tests.deployed import (
    DEFAULTED,
    FILES,
    PROSE,
    WIDGETS,
    put_in_force,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.method.tests.policy_files import REFERENCES
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.values.checked_policy import CHECKS
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)

GADGETS = ("github", "example-org/gadgets")

#: Business development's deployment: one reviewer, site, on the
#: pull-request layer alone, at the same cadence as the other tenant's.
SITE = {
    "pace-layers.toml": DEFAULTED.split("[process.security-stocktake]")[0]
    + '[layer.pull-request]\ncadence = "event"\ndefault_boundary = "60s"\n'
    'processes = ["evaluate-pull-request"]\n',
    "site/reviewer.md": PROSE.replace("prose", "site"),
    f"{REFERENCES.replace('prose', 'site')}/policies/P-01-example.md": FILES[
        f"{REFERENCES}/policies/P-01-example.md"
    ],
    f"{REFERENCES.replace('prose', 'site')}/doctrine/01-voice.md": FILES[
        f"{REFERENCES}/doctrine/01-voice.md"
    ],
    # A prose of its own, of the same id as default's (ADR 012).
    "prose/reviewer.md": PROSE,
    f"{REFERENCES}/policies/P-01-example.md": FILES[
        f"{REFERENCES}/policies/P-01-example.md"
    ],
    f"{REFERENCES}/doctrine/01-voice.md": FILES[
        f"{REFERENCES}/doctrine/01-voice.md"
    ],
}


def two_tenants(database_url: str) -> None:
    """Default's deployment in force, with prose and security set on
    widgets, and business development's, with site set on gadgets and
    its own prose, which it holds too, set on gadgets."""
    put_in_force(database_url)
    deploying_over(database_url, None, CHECKS).deploy.execute(
        DeployPoliciesRequest(
            repository="example-org/site-policies",
            commit="d" * 40,
            files=tuple(
                PolicyFile(path=path, text=text)
                for path, text in sorted(SITE.items())
            ),
            sent_by="a test",
            tenant="business-development",
        )
    )
    for gnome in ("site", "prose"):
        SqlAlchemyGnomeSettings(database_url).save(
            GnomeSetting(
                forge=GADGETS[0],
                repo=GADGETS[1],
                gnome=gnome,
                behaviour="observe",
                tenant="business-development",
                set_by="a test",
                set_at=datetime.now(UTC),
            )
        )


def test_each_worker_watches_the_repositories_its_own_gnomes_judge(
    database_url: str,
) -> None:
    two_tenants(database_url)
    deployments = SqlAlchemyPolicyDeployments(database_url)
    ours = reviewers_in_force(deployments, CHECKS)
    theirs = reviewers_in_force(
        deployments, CHECKS, tenant="business-development"
    )
    assert ours is not None and theirs is not None
    assert set(ours.agents) == {"prose", "security"}
    assert set(theirs.agents) == {"prose", "site"}
    assert watched_in(own_settings(database_url, ours)) == (
        f"{WIDGETS[0]}:{WIDGETS[1]}",
    )
    assert watched_in(own_settings(database_url, theirs)) == (
        f"{GADGETS[0]}:{GADGETS[1]}",
    )


def test_the_worker_reviews_by_the_deployment_of_the_tenant_named(
    database_url: str,
) -> None:
    two_tenants(database_url)
    parts = parts_from_environment(
        {"DATABASE_URL": database_url, "TENANT": "business-development"}
    )
    assert (
        parts.lines[0]
        == (
            "reviews under example-org/site-policies at "
            + "d" * 40
            + ", content "
            + SqlAlchemyPolicyDeployments(database_url)
            .in_force("business-development")  # type: ignore[union-attr]
            .content_hash[:12]
            + ", for business-development"
        )
    )
    assert parts.lines[1] == "holds the layers pull-request"


def test_a_tenant_with_no_deployment_reviews_nothing_and_says_whose(
    database_url: str,
) -> None:
    put_in_force(database_url)
    parts = parts_from_environment(
        {"DATABASE_URL": database_url, "TENANT": "delivery-assurance"}
    )
    assert parts.workflows == ()
    assert parts.lines == (
        "reviews nothing: no policy deployment is in force for "
        "delivery-assurance",
    )
