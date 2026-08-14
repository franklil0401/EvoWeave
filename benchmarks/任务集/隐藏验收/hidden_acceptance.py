"""Task-specific black-box acceptance checks executed from a candidate worktree."""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path


def _prepare_imports() -> None:
    root = Path.cwd()
    sys.path.insert(0, str(root))
    source = root / "src"
    if source.is_dir():
        sys.path.insert(0, str(source))


def _single_case() -> None:
    calculator = importlib.import_module("calculator")
    assert calculator.calculate_discount(100, "vip") == 90
    assert calculator.calculate_discount(100, "Vip") == 90
    assert calculator.calculate_discount(100, "VIP") == 90
    assert calculator.calculate_discount(100, "OTHER") == 100


def _member_case() -> None:
    calculator = importlib.import_module("calculator")
    assert calculator.calculate_discount(100, "MEMBER") == 95
    assert calculator.calculate_discount(100, "VIP") == 90
    assert calculator.calculate_discount(100, "OTHER") == 100


def _serial_case() -> None:
    models = importlib.import_module("shop.models")
    pricing = importlib.import_module("shop.pricing")
    service = importlib.import_module("shop.service")
    parameters = tuple(inspect.signature(pricing.calculate_discount).parameters)
    assert parameters == ("total", "customer")
    vip = models.Customer("VIP")
    assert pricing.calculate_discount(100, vip) == 90
    assert service.checkout_total(100, vip) == 90


def _parallel_case() -> None:
    models = importlib.import_module("shop.models")
    pricing = importlib.import_module("shop.pricing")
    assert models.Customer(" vip ").normalized_type == "VIP"
    assert pricing.calculate_discount(100, " vip ") == 90
    assert pricing.calculate_discount(100, "OTHER") == 100


def _low_confidence_case() -> None:
    models = importlib.import_module("shop.models")
    service = importlib.import_module("shop.service")
    assert service.checkout_total(100, models.Customer(" vip ")) == 90
    expected = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass(frozen=True)\n"
        "class Customer:\n"
        "    customer_type: str\n"
    )
    assert Path("src/shop/models.py").read_text(encoding="utf-8") == expected


def _baseline_failure_case() -> None:
    app = importlib.import_module("app")
    try:
        app.divide(1, 0)
    except ValueError as exc:
        message = str(exc).casefold()
        assert "right" in message
        assert "zero" in message
    else:
        raise AssertionError("divide(1, 0) must raise ValueError")


def _write_conflict_case() -> None:
    pricing = importlib.import_module("shop.pricing")
    assert pricing.calculate_discount(100, " vip ") == 85
    assert pricing.calculate_discount(100, "OTHER") == 100


def _high_risk_case() -> None:
    calculator = importlib.import_module("calculator")
    parameters = inspect.signature(calculator.calculate_discount).parameters
    assert "authorized" in parameters
    assert parameters["authorized"].kind is inspect.Parameter.KEYWORD_ONLY
    try:
        calculator.calculate_discount(100, "VIP")
    except PermissionError:
        pass
    else:
        raise AssertionError("unauthorized discount must raise PermissionError")
    assert calculator.calculate_discount(100, "VIP", authorized=True) == 90


def _image_ui_case() -> None:
    html = Path("web/login.html").read_text(encoding="utf-8")
    assert 'data-testid="discount-login-hint"' in html
    assert "登录后可查看专属折扣" in html
    calculator = Path("calculator.py").read_text(encoding="utf-8")
    assert 'customer_type == "VIP"' in calculator


def _image_architecture_case() -> None:
    models = importlib.import_module("shop.models")
    pricing = importlib.import_module("shop.pricing")
    service = importlib.import_module("shop.service")
    assert not hasattr(pricing, "calculate_discount")
    assert pricing.discount_amount(100, "VIP") == 10
    assert pricing.discount_amount(100, "OTHER") == 0
    assert service.checkout_total(100, models.Customer("VIP")) == 90


def _pricing_case() -> None:
    pricing = importlib.import_module("shop.pricing")
    assert pricing.calculate_discount(100, "vip") == 90
    assert pricing.calculate_discount(100, "Vip") == 90
    assert pricing.calculate_discount(100, "VIP") == 90
    assert pricing.calculate_discount(100, "OTHER") == 100


_CHECKS = {
    "bench-01-single-file": _single_case,
    "bench-02-single-module": _member_case,
    "bench-03-multi-serial": _serial_case,
    "bench-04-multi-parallel": _parallel_case,
    "bench-05-low-confidence": _low_confidence_case,
    "bench-06-baseline-failure": _baseline_failure_case,
    "bench-07-write-conflict": _write_conflict_case,
    "bench-08-high-risk": _high_risk_case,
    "bench-09-image-ui": _image_ui_case,
    "bench-10-image-architecture": _image_architecture_case,
    "bench-11-image-negative": _pricing_case,
    "bench-12-model-fallback": _single_case,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in _CHECKS:
        print("usage: hidden_acceptance.py <benchmark-id>", file=sys.stderr)
        return 2
    _prepare_imports()
    _CHECKS[sys.argv[1]]()
    print(f"PASS {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
