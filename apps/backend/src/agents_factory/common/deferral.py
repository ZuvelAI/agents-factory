class JobDeferred(RuntimeError):
    """No provider/business work occurred; reschedule without charging a retry."""

    def __init__(self, delay_seconds: float) -> None:
        if not 0 < delay_seconds <= 3600:
            raise ValueError("invalid job deferral")
        self.delay_seconds = delay_seconds
        super().__init__("capacity_deferred")
