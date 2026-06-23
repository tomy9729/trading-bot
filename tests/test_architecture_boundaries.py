import ast
from pathlib import Path

from src.config.runtime_paths import PROJECT_ROOT


def test_broker_package_does_not_depend_on_database_or_services():
    imports = _get_package_imports(PROJECT_ROOT / "src" / "broker")

    assert not any(name.startswith("src.db") for name in imports)
    assert not any(name.startswith("src.services") for name in imports)


def test_dashboard_api_does_not_depend_on_trading_runtime_packages():
    imports = _get_package_imports(PROJECT_ROOT / "apps" / "api")
    forbidden_prefixes = (
        "src.broker",
        "src.runner",
        "src.risk",
        "src.strategy",
        "src.services.order_execution_service",
        "src.services.trading_account_service",
        "src.services.trading_order_service",
    )

    assert not any(name.startswith(forbidden_prefixes) for name in imports)


def _get_package_imports(package_path: Path) -> set[str]:
    imports = set()
    for path in package_path.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports
