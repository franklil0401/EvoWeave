import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from evoweave.benchmarking.materializer import FixtureMaterializer
from evoweave.benchmarking.suite_loader import load_benchmark_suite

_PROJECT_ROOT = Path(__file__).parents[2]
_SUITE_PATH = _PROJECT_ROOT / "benchmarks/任务集/第一版任务集.json"
_HIDDEN = _PROJECT_ROOT / "benchmarks/任务集/隐藏验收/hidden_acceptance.py"


@pytest.mark.parametrize("task_index", range(12))
def test_hidden_acceptance_rejects_baseline_and_accepts_known_good_change(
    tmp_path: Path,
    task_index: int,
) -> None:
    suite, _digest = load_benchmark_suite(_SUITE_PATH)
    task = suite.tasks[task_index]
    repository = (
        FixtureMaterializer(_PROJECT_ROOT)
        .materialize(
            task,
            tmp_path / task.benchmark_id,
        )
        .path
    )

    assert _run_hidden(repository, task.benchmark_id).returncode != 0
    _ORACLE_CHANGES[task.benchmark_id](repository)

    completed = _run_hidden(repository, task.benchmark_id)
    assert completed.returncode == 0, completed.stderr


def _run_hidden(repository: Path, benchmark_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(_HIDDEN), benchmark_id),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _write(repository: Path, path: str, content: str) -> None:
    destination = repository / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _single(repository: Path) -> None:
    _write(
        repository,
        "calculator.py",
        "def calculate_discount(total: float, customer_type: str) -> float:\n"
        '    if customer_type.upper() == "VIP":\n'
        "        return total * 0.9\n"
        "    return total\n",
    )


def _member(repository: Path) -> None:
    _write(
        repository,
        "calculator.py",
        "def calculate_discount(total: float, customer_type: str) -> float:\n"
        '    if customer_type == "VIP":\n'
        "        return total * 0.9\n"
        '    if customer_type == "MEMBER":\n'
        "        return total * 0.95\n"
        "    return total\n",
    )


def _serial(repository: Path) -> None:
    _write(
        repository,
        "src/shop/pricing.py",
        "from shop.models import Customer\n\n\n"
        "def calculate_discount(total: float, customer: Customer) -> float:\n"
        '    if customer.customer_type == "VIP":\n'
        "        return total * 0.9\n"
        "    return total\n",
    )
    _write(
        repository,
        "src/shop/service.py",
        "from shop.models import Customer\n"
        "from shop.pricing import calculate_discount\n\n\n"
        "def checkout_total(total: float, customer: Customer) -> float:\n"
        "    return calculate_discount(total, customer)\n",
    )


def _parallel(repository: Path) -> None:
    _write(
        repository,
        "src/shop/models.py",
        "from dataclasses import dataclass\n\n\n"
        "@dataclass(frozen=True)\n"
        "class Customer:\n"
        "    customer_type: str\n\n"
        "    @property\n"
        "    def normalized_type(self) -> str:\n"
        "        return self.customer_type.strip().upper()\n",
    )
    _pricing_normalized(repository)


def _pricing_normalized(repository: Path) -> None:
    _write(
        repository,
        "src/shop/pricing.py",
        "def calculate_discount(total: float, customer_type: str) -> float:\n"
        '    if customer_type.strip().upper() == "VIP":\n'
        "        return total * 0.9\n"
        "    return total\n",
    )


def _baseline_failure(repository: Path) -> None:
    _write(
        repository,
        "app.py",
        "def divide(left: int, right: int) -> float:\n"
        "    if right == 0:\n"
        '        raise ValueError("right cannot be zero")\n'
        "    return left / right\n",
    )


def _conflict(repository: Path) -> None:
    _write(
        repository,
        "src/shop/pricing.py",
        "def calculate_discount(total: float, customer_type: str) -> float:\n"
        '    if customer_type.strip().upper() == "VIP":\n'
        "        return total * 0.85\n"
        "    return total\n",
    )


def _high_risk(repository: Path) -> None:
    _write(
        repository,
        "calculator.py",
        "def calculate_discount(\n"
        "    total: float, customer_type: str, *, authorized: bool = False\n"
        ") -> float:\n"
        "    if not authorized:\n"
        '        raise PermissionError("discount is not authorized")\n'
        '    if customer_type == "VIP":\n'
        "        return total * 0.9\n"
        "    return total\n",
    )


def _image_ui(repository: Path) -> None:
    _write(
        repository,
        "web/login.html",
        '<p data-testid="discount-login-hint">登录后可查看专属折扣</p>\n',
    )


def _image_architecture(repository: Path) -> None:
    _write(
        repository,
        "src/shop/pricing.py",
        "def discount_amount(total: float, customer_type: str) -> float:\n"
        '    return total * 0.1 if customer_type == "VIP" else 0\n',
    )
    _write(
        repository,
        "src/shop/service.py",
        "from shop.models import Customer\n"
        "from shop.pricing import discount_amount\n\n\n"
        "def checkout_total(total: float, customer: Customer) -> float:\n"
        "    return total - discount_amount(total, customer.customer_type)\n",
    )


def _pricing_case(repository: Path) -> None:
    _write(
        repository,
        "src/shop/pricing.py",
        "def calculate_discount(total: float, customer_type: str) -> float:\n"
        '    if customer_type.upper() == "VIP":\n'
        "        return total * 0.9\n"
        "    return total\n",
    )


_ORACLE_CHANGES: dict[str, Callable[[Path], None]] = {
    "bench-01-single-file": _single,
    "bench-02-single-module": _member,
    "bench-03-multi-serial": _serial,
    "bench-04-multi-parallel": _parallel,
    "bench-05-low-confidence": _pricing_normalized,
    "bench-06-baseline-failure": _baseline_failure,
    "bench-07-write-conflict": _conflict,
    "bench-08-high-risk": _high_risk,
    "bench-09-image-ui": _image_ui,
    "bench-10-image-architecture": _image_architecture,
    "bench-11-image-negative": _pricing_case,
    "bench-12-model-fallback": _single,
}
