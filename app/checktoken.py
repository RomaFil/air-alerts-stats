"""Перевірка токена alerts.in.ua перед перемиканням джерела.

Запускається одноразовим контейнером. Нічого не пише в БД — тільки з'ясовує,
чи приймає API токен і чи віддає історію. Код виходу 0 = токен робочий.
"""
from __future__ import annotations

import sys

from .providers import ProviderError, get_provider


def main() -> int:
    try:
        provider = get_provider("alerts_in_ua")
    except ProviderError as e:
        print(f"✗ {e}")
        return 1

    try:
        active = provider.fetch_active()
        print(f"✓ активні тривоги: {len(active) if active is not None else '304 (не змінилось)'}")
    except ProviderError as e:
        print(f"✗ живий статус: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"✗ живий статус: {type(e).__name__}: {e}")
        return 1

    # Найважливіше: чи доступна історія. Саме заради неї ми й перемикаємось,
    # а вона на окремому ліміті й може бути закрита для безкоштовного тарифу.
    try:
        history = provider.fetch_history(31)  # м. Київ
        print(f"✓ історія за місяць (м. Київ): {len(history)} записів")
        if history:
            oldest = min(a["started_at"] for a in history)
            closed = sum(1 for a in history if a["finished_at"])
            print(f"  найдавніша: {oldest}, із завершенням: {closed}/{len(history)}")
    except ProviderError as e:
        print(f"✗ історія: {e}")
        print("  Живий статус працює, але історії немає — перемикатись немає сенсу,")
        print("  siren дає більшу гранулярність за ті самі можливості.")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"✗ історія: {type(e).__name__}: {e}")
        return 2
    finally:
        provider.close()

    print("✓ токен робочий, історія доступна")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
