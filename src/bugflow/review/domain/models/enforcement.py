"""What publishing may do on one repository (ADR 008).

Each gnome's setting on the repository decides it: a gnome at
``advise`` or ``gate`` has its comment and its commit status written to
the forge, and a gnome at ``gate`` fails its status on a ``fail``
verdict. A gnome at ``observe`` is judged and journalled, and nothing of
it reaches the forge.

The label says what the review as a whole says. The gnomes at ``gate``
decide it where any gates. Where none does, the gnomes at ``advise``
decide it, so an advised repository's label is advice and a gnome at
``observe`` never moves a label the forge shows. Where none publishes,
every gnome that judges decides it, so an observed repository's journal
records what its label would be.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Enforcement:
    #: The gnomes, by agent id, that judge the repository.
    judging: frozenset[str] = frozenset()
    #: The gnomes whose comment and status are written to the forge.
    #: Each also judges.
    publishing: frozenset[str] = frozenset()
    #: The gnomes whose status fails on a ``fail`` verdict, and whose
    #: verdicts decide the label where any gates. Each also publishes.
    gating: frozenset[str] = frozenset()
    #: The share of warnings, from 0 to 1, that are kept out of the
    #: pull request on purpose. Comparing what happens to a warning
    #: nobody saw with one somebody could have seen shows whether
    #: warnings are acted on. The default, 0, keeps none out.
    withholds: float = 0.0
    #: The gnomes whose verdicts may decide a label, as their manifests
    #: say; None, every gnome. A gnome that gives no verdict on a pull
    #: request's head, as one only a stocktake runs, would hold the
    #: label at work in progress, and its manifest says it does not
    #: govern.
    may_decide: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not self.gating <= self.publishing:
            raise ValueError(
                f"{', '.join(sorted(self.gating - self.publishing))} gates "
                "and does not publish; a gnome that gates publishes"
            )
        if not self.publishing <= self.judging:
            raise ValueError(
                f"{', '.join(sorted(self.publishing - self.judging))} "
                "publishes and does not judge; a gnome that publishes judges"
            )

    @property
    def deciding(self) -> frozenset[str]:
        """The gnomes whose verdicts decide the label, of those that may
        decide one: those at gate; where none gates, those that publish,
        so a gnome on observe never moves a label the forge shows; and
        where none publishes, every gnome that judges, for the label the
        journal records."""

        def among(gnomes: frozenset[str]) -> frozenset[str]:
            if self.may_decide is None:
                return gnomes
            return gnomes & self.may_decide

        return (
            among(self.gating) or among(self.publishing) or among(self.judging)
        )

    @property
    def publishes(self) -> bool:
        """Whether anything reaches the forge: a comment, the label or a
        status."""
        return bool(self.publishing)


def fails(
    enforcement: Enforcement, agent_id: str, verdict: str | None
) -> bool:
    """Whether a gnome's verdict makes its commit status fail here."""
    return agent_id in enforcement.gating and verdict == "fail"
