from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParserBase[T_IN, T_OUT](ABC):
    _source: list[T_IN] = field(default_factory=list)
    _result: list[T_OUT] = field(default_factory=list)
    _value: list[T_IN] = field(default_factory=list)
    _consumed: int = 0

    def parse(self, source: list[T_IN]) -> list[T_OUT]:
        self._source = source
        self._result = []
        self._value = []
        self._consumed = 0
        return self._parse()

    @abstractmethod
    def _parse(self) -> list[T_OUT]:
        raise NotImplementedError

    @abstractmethod
    def _get_eof_token(self) -> T_IN:
        raise NotImplementedError

    def _peek_curr(self) -> T_IN:
        return self._peek_n(0)

    def _peek_next(self) -> T_IN:
        return self._peek_n(1)

    def _peek_n(self, n: int) -> T_IN:
        shift = self._consumed + n
        if shift < len(self._source):
            return self._source[shift]
        return self._get_eof_token()

    def _is_at_end(self) -> bool:
        return self._consumed >= len(self._source)

    def _consume(self) -> T_IN:
        token = self._peek_curr()
        if token != self._get_eof_token():
            self._value += [token]
            self._consumed += 1
        return token

    def _push(self, token: T_OUT):
        self._result.append(token)
        self._drop()

    def _drop(self):
        self._value = []
