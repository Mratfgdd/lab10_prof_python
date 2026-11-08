"""Прогноз відсотків: оптимізація, залишена після експериментів ЛР9.

10 % річних, щоденна капіталізація, відсотки за день округлюються до копійки (half-up).
У ЛР9 NumPy-версія виявилася в 8 разів швидшою за цикли Python і не змінює результату:
365 векторних кроків для всіх рахунків одночасно, цілі копійки - без похибки float.
"""

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

DAILY_DIVISOR = 3650
HALF = DAILY_DIVISOR // 2


def accrue_numpy(balances: npt.NDArray[np.int64], days: int) -> npt.NDArray[np.int64]:
    result = balances.copy()
    for _ in range(days):
        result += (result + HALF) // DAILY_DIVISOR
    return result


def accrue_python(balance: int, days: int) -> int:
    """Еталон (baseline ЛР9) для тестів."""
    for _ in range(days):
        balance += (balance + HALF) // DAILY_DIVISOR
    return balance


def forecast(balances_cents: Sequence[int], days: int) -> tuple[int, int]:
    """(сума зараз, сума через days днів) у копійках."""
    current = np.asarray(balances_cents, dtype=np.int64)
    return int(current.sum()), int(accrue_numpy(current, days).sum())
