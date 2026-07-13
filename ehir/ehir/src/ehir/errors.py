class EhirCompileError(RuntimeError):
    """Stable user-facing compile error for language/semantic diagnostics."""

    def __init__(self, message: str, *, code: str = "EHIR0000"):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
