"""What each gnome does on each repository, held in memory, for tests."""

from bugflow.review.domain.models.gnome_setting import GnomeSetting


class InMemoryGnomeSettings:
    def __init__(self, *settings: GnomeSetting) -> None:
        self._held: dict[tuple[str, str, str], GnomeSetting] = {}
        for one in settings:
            self.save(one)

    def settings_of(self, forge: str, repo: str) -> tuple[GnomeSetting, ...]:
        return tuple(
            one
            for one in self.settings()
            if (one.forge, one.repo) == (forge, repo)
        )

    def settings(self) -> tuple[GnomeSetting, ...]:
        return tuple(self._held[key] for key in sorted(self._held))

    def save(self, setting: GnomeSetting) -> None:
        self._held[(setting.forge, setting.repo, setting.gnome)] = setting
