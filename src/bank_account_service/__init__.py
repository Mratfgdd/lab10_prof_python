"""Bank Account Service: REST API банківських рахунків (варіант 4, ЛР1-ЛР10)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bank-account-service")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
