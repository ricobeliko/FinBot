"""Testes unitários para o gerador de grid e presets de parâmetros do FinBot Lab."""

import unittest

from finbot.lab.grid import (
    PRESET_FULL,
    PRESET_SMOKE,
    PRESET_STANDARD,
    generate_sma_grid,
    validate_preset_execution,
)
from finbot.lab.models import SMAParams


class TestLabGrid(unittest.TestCase):
    """Bateria de testes para regras de combinação e proteção contra grids acidentais."""

    def test_smaparams_validation(self) -> None:
        """SMAParams deve rejeitar short >= long ou short < 1."""
        with self.assertRaises(ValueError):
            SMAParams(short_window=10, long_window=10)  # short == long

        with self.assertRaises(ValueError):
            SMAParams(short_window=15, long_window=10)  # short > long

        with self.assertRaises(ValueError):
            SMAParams(short_window=0, long_window=10)   # short < 1

        # Válido
        params = SMAParams(short_window=5, long_window=10)
        self.assertEqual(params.short_window, 5)
        self.assertEqual(params.long_window, 10)

    def test_grid_rule_short_strictly_less_than_long(self) -> None:
        """Garante que em todos os presets gerados short_window < long_window."""
        for preset in (PRESET_SMOKE, PRESET_STANDARD):
            grid = generate_sma_grid(preset=preset)
            self.assertGreater(len(grid), 0)
            for p in grid:
                self.assertLess(
                    p.short_window,
                    p.long_window,
                    f"Violação detectada no preset {preset}: short={p.short_window} >= long={p.long_window}",
                )

        # Full com confirmação
        grid_full = generate_sma_grid(preset=PRESET_FULL, confirm_full=True)
        self.assertGreater(len(grid_full), 0)
        for p in grid_full:
            self.assertLess(p.short_window, p.long_window)

    def test_grid_smoke_preset(self) -> None:
        """Preset SMOKE deve conter poucas combinações (exatamente 9)."""
        grid = generate_sma_grid(preset=PRESET_SMOKE)
        self.assertEqual(len(grid), 9)
        # Verifica se (5, 10) está presente
        self.assertIn(SMAParams(5, 10), grid)

    def test_grid_full_requires_confirmation(self) -> None:
        """Preset FULL deve disparar ValueError se confirm_full for False."""
        with self.assertRaises(ValueError) as ctx:
            generate_sma_grid(preset=PRESET_FULL, confirm_full=False)
        self.assertIn("--confirm-full", str(ctx.exception))

        with self.assertRaises(ValueError):
            validate_preset_execution(preset=PRESET_FULL, confirm_full=False)

    def test_invalid_preset_rejected(self) -> None:
        """Presets desconhecidos devem disparar ValueError."""
        with self.assertRaises(ValueError):
            generate_sma_grid(preset="super_grid")

    def test_deterministic_order(self) -> None:
        """Chamadas sucessivas devem produzir exatamente os mesmos pares na mesma ordem."""
        grid1 = generate_sma_grid(preset=PRESET_SMOKE)
        grid2 = generate_sma_grid(preset=PRESET_SMOKE)
        self.assertEqual(grid1, grid2)


if __name__ == "__main__":
    unittest.main()
