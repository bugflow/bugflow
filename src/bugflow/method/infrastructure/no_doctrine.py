"""The doctrine of a server with nothing deployed."""

from bugflow.method.domain.models.doctrine import Doctrine


class NoDoctrine:
    """Implements ``DoctrineRepository`` with an empty text.

    A server with no reviewer and no policy judges nothing, so nothing
    reads the text; what asks for the doctrine still gets one, and its
    version says that nothing was in force.
    """

    def load(self) -> Doctrine:
        return Doctrine(text="")
