"""Módulo gerador de grid de parâmetros para o FinBot Lab.

Gera combinações sistemáticas de janelas de médias móveis (short_window e long_window),
assegurando rigorosamente a regra short_window < long_window e determinismo de ordenação.
"""

from typing import Sequence
from finbot.lab.models import SMAParams

PRESET_SMOKE = "smoke"
PRESET_STANDARD = "standard"
PRESET_FULL = "full"
VALID_PRESETS = (PRESET_SMOKE, PRESET_STANDARD, PRESET_FULL)


def validate_preset_execution(preset: str, confirm_full: bool = False) -> None:
    """Valida se o preset solicitado é válido e se possui as confirmações necessárias."""
    clean_preset = preset.strip().lower()
    if clean_preset not in VALID_PRESETS:
        raise ValueError(
            f"Preset inválido: '{preset}'. Presets disponíveis: {', '.join(VALID_PRESETS)}."
        )

    if clean_preset == PRESET_FULL and not confirm_full:
        raise ValueError(
            "O preset 'full' executa um grid pesado de alta intensidade projetado para o PC forte. "
            "Para autorizar a execução consciente, informe explicitamente o parâmetro '--confirm-full'."
        )


def generate_sma_grid(
    preset: str = PRESET_SMOKE,
    confirm_full: bool = False,
    custom_short: Sequence[int] | None = None,
    custom_long: Sequence[int] | None = None,
) -> list[SMAParams]:
    """Gera a lista de combinações (short_window, long_window) para o sweep.

    Garante:
    - short_window < long_window em 100% dos pares gerados.
    - Ordenação determinística.
    - Proteção contra acionamento acidental do preset FULL.
    """
    validate_preset_execution(preset, confirm_full=confirm_full)
    clean_preset = preset.strip().lower()

    if custom_short is not None and custom_long is not None:
        short_values = sorted(set(custom_short))
        long_values = sorted(set(custom_long))
    elif clean_preset == PRESET_SMOKE:
        short_values = [3, 5, 8]
        long_values = [10, 15, 20]
    elif clean_preset == PRESET_STANDARD:
        short_values = list(range(3, 16, 2))  # 3, 5, 7, 9, 11, 13, 15
        long_values = [10, 14, 18, 22, 26, 30, 35, 40, 45, 50]
    elif clean_preset == PRESET_FULL:
        short_values = list(range(2, 25, 1))  # 2 até 24
        long_values = list(range(6, 61, 2))   # 6 até 60
    else:
        raise ValueError(f"Preset não suportado: {preset}")

    grid: list[SMAParams] = []
    for s in short_values:
        for l in long_values:
            if s < l:
                grid.append(SMAParams(short_window=s, long_window=l))

    # Ordenação determinística explícita
    grid.sort(key=lambda p: (p.short_window, p.long_window))
    return grid
