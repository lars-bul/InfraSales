"""Expected failures: what they are recorded as, without details."""


class ExpectedError(Exception):
    """A failure InfraSales expects and records: a Feed it cannot read, a document it skips.

    `reason` is what is recorded (a Feed's `last_error`, a run's failed Feeds): short and fixed
    ("blocked", "http 404", "unreadable"), never a URL or a message. Subclasses set it as a class
    attribute, or per instance when it depends on the case.
    """

    reason: str = "failed"
