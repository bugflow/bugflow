"""What the interfaces here raise."""


class ObjectStoreError(Exception):
    """The object could not be written, or the store could not be read.

    Not the answer for an object that is not there: reading one answers
    None, and asking after one answers False.
    """
