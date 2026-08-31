class AgentRuntimeError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class RuntimeToolLimitExceeded(AgentRuntimeError):
    def __init__(self) -> None:
        super().__init__("runtime_tool_limit_exceeded", retryable=False)
