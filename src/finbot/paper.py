"""Módulo de execução de Paper Trading local persistente para a FASE 5.

Simula compras e vendas com capital fictício sobre dados reais públicos de mercado.
Persiste estado e transações localmente no SQLite.
NENHUMA ordem é enviada a qualquer exchange.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
import sys

from finbot.config import Config, get_config
from finbot.exchange import CandleData, close_exchange, create_exchange, fetch_candles, fetch_ticker
from finbot.storage import PaperAccount, PaperPosition, PaperStorage, PaperTrade
from finbot.strategy import Signal, evaluate_sma_crossover


def timeframe_to_ms(timeframe: str) -> int:
    """Converte identificador de timeframe (ex: '1m', '5m', '1h') para milissegundos."""
    if not timeframe:
        raise ValueError("Timeframe não pode ser vazio.")
    unit = timeframe[-1].lower()
    try:
        val = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"Formato de timeframe inválido: '{timeframe}'") from exc

    if unit == "m":
        return val * 60 * 1000
    if unit == "h":
        return val * 60 * 60 * 1000
    if unit == "d":
        return val * 24 * 60 * 60 * 1000
    if unit == "w":
        return val * 7 * 24 * 60 * 60 * 1000
    raise ValueError(f"Unidade de timeframe não suportada: '{unit}' em '{timeframe}'")


def filter_closed_candles(
    candles: list[CandleData],
    timeframe: str,
    now_ms: int | None = None,
) -> list[CandleData]:
    """Filtra e retorna apenas candles cujo fechamento já ocorreu.

    Um candle iniciado em t com duração d fecha no instante t + d.
    Se now_ms < t + d, o candle ainda está em formação e é descartado para decisões.
    """
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    duration_ms = timeframe_to_ms(timeframe)
    return [c for c in candles if (c.timestamp + duration_ms) <= now_ms]


@dataclass(frozen=True)
class PaperCycleResult:
    """Resultado da execução de um ciclo isolado (one-shot) de Paper Trading."""

    exchange: str
    symbol: str
    timeframe: str
    closed_candle_time: str
    closed_candle_timestamp: int
    signal: Signal
    signal_reason: str
    trade_action: str
    executed_trade: PaperTrade | None
    account: PaperAccount
    position: PaperPosition
    trades_count: int
    message: str = ""


def execute_paper_cycle(
    storage: PaperStorage,
    config: Config,
    now_ms: int | None = None,
    ticker_override: float | None = None,
    candles_override: list[CandleData] | None = None,
) -> PaperCycleResult:
    """Executa um ciclo one-shot de forward testing em Paper Trading.

    Premissa de Execução:
    'Paper fills assume immediate execution at observed public market price plus configured commission.'
    """
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # 1. Obtenção de dados públicos de mercado
    if candles_override is not None and ticker_override is not None:
        raw_candles = candles_override
        last_price = ticker_override
    else:
        ex = create_exchange(config.exchange_id)
        try:
            ticker = fetch_ticker(ex, config.symbol)
            raw_candles = fetch_candles(
                ex,
                symbol=config.symbol,
                timeframe=config.paper_timeframe,
                limit=config.paper_candle_limit,
            )
            last_price = ticker.last if ticker.last is not None else raw_candles[-1].close
        finally:
            close_exchange(ex)

    # 2. Filtragem de candles fechados
    closed_candles = filter_closed_candles(raw_candles, config.paper_timeframe, now_ms=now_ms)
    required_candles = config.long_window + 1

    account = storage.get_account()
    position = storage.get_position()
    trades_count = storage.get_trades_count()

    if len(closed_candles) < required_candles:
        return PaperCycleResult(
            exchange=config.exchange_id,
            symbol=config.symbol,
            timeframe=config.paper_timeframe,
            closed_candle_time="N/A",
            closed_candle_timestamp=0,
            signal=Signal.HOLD,
            signal_reason=f"Candles fechados insuficientes: {len(closed_candles)}/{required_candles}",
            trade_action="INSUFFICIENT_CANDLES",
            executed_trade=None,
            account=account,
            position=position,
            trades_count=trades_count,
            message="Dados insuficientes para cálculo de estratégia.",
        )

    latest_closed = closed_candles[-1]

    # 3. Deduplicação de candle: verifica se já foi processado
    last_processed = storage.get_last_processed_candle_timestamp()
    if last_processed is not None and latest_closed.timestamp <= last_processed:
        return PaperCycleResult(
            exchange=config.exchange_id,
            symbol=config.symbol,
            timeframe=config.paper_timeframe,
            closed_candle_time=latest_closed.formatted_time,
            closed_candle_timestamp=latest_closed.timestamp,
            signal=Signal.HOLD,
            signal_reason="Candle já processado em ciclo anterior.",
            trade_action="NO_NEW_CANDLE",
            executed_trade=None,
            account=account,
            position=position,
            trades_count=trades_count,
            message="No new closed candle.",
        )

    # 4. Avaliação determinística da estratégia
    eval_res = evaluate_sma_crossover(
        data=closed_candles,
        short_window=config.short_window,
        long_window=config.long_window,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    commission_rate = Decimal(str(config.paper_commission))
    trade_price = Decimal(str(last_price))

    # 5. Processamento dos sinais segundo o modelo Spot LONG
    if eval_res.signal == Signal.BUY:
        if position.side == "LONG":
            storage.record_candle_processed(latest_closed.timestamp)
            return PaperCycleResult(
                exchange=config.exchange_id,
                symbol=config.symbol,
                timeframe=config.paper_timeframe,
                closed_candle_time=latest_closed.formatted_time,
                closed_candle_timestamp=latest_closed.timestamp,
                signal=Signal.BUY,
                signal_reason=eval_res.reason,
                trade_action="BUY_IGNORED_POSITION_EXISTS",
                executed_trade=None,
                account=account,
                position=position,
                trades_count=trades_count,
                message="BUY ignorado: posição já aberta (uma posição por vez).",
            )

        # Abertura de posição Spot LONG com notional fixo
        notional = Decimal(str(config.paper_trade_notional))
        fee = (notional * commission_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_cost = notional + fee

        if account.usdt_balance < total_cost:
            storage.record_candle_processed(latest_closed.timestamp)
            return PaperCycleResult(
                exchange=config.exchange_id,
                symbol=config.symbol,
                timeframe=config.paper_timeframe,
                closed_candle_time=latest_closed.formatted_time,
                closed_candle_timestamp=latest_closed.timestamp,
                signal=Signal.BUY,
                signal_reason=eval_res.reason,
                trade_action="BUY_INSUFFICIENT_FUNDS",
                executed_trade=None,
                account=account,
                position=position,
                trades_count=trades_count,
                message=f"BUY cancelado: saldo USDT insuficiente ({account.usdt_balance} < {total_cost}).",
            )

        quantity = (notional / trade_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        new_usdt = account.usdt_balance - total_cost
        new_btc = account.btc_balance + quantity

        new_account = PaperAccount(
            usdt_balance=new_usdt,
            btc_balance=new_btc,
            updated_at=now_iso,
        )
        new_position = PaperPosition(
            side="LONG",
            quantity=quantity,
            cost_basis=total_cost,
            entry_price=trade_price,
            entry_timestamp=now_iso,
        )
        pending_trade = PaperTrade(
            id=None,
            timestamp=now_iso,
            candle_timestamp=latest_closed.timestamp,
            symbol=config.symbol,
            side="BUY",
            price=trade_price,
            quantity=quantity,
            notional=notional,
            fee=fee,
            realized_pnl=None,
        )

        executed_trade = storage.execute_trade_transaction(
            new_account=new_account,
            new_position=new_position,
            trade=pending_trade,
            candle_timestamp=latest_closed.timestamp,
        )

        return PaperCycleResult(
            exchange=config.exchange_id,
            symbol=config.symbol,
            timeframe=config.paper_timeframe,
            closed_candle_time=latest_closed.formatted_time,
            closed_candle_timestamp=latest_closed.timestamp,
            signal=Signal.BUY,
            signal_reason=eval_res.reason,
            trade_action="BUY_EXECUTED",
            executed_trade=executed_trade,
            account=new_account,
            position=new_position,
            trades_count=trades_count + 1,
            message="Paper BUY executado com sucesso.",
        )

    if eval_res.signal == Signal.SELL:
        if position.side != "LONG" or position.quantity <= Decimal("0"):
            storage.record_candle_processed(latest_closed.timestamp)
            return PaperCycleResult(
                exchange=config.exchange_id,
                symbol=config.symbol,
                timeframe=config.paper_timeframe,
                closed_candle_time=latest_closed.formatted_time,
                closed_candle_timestamp=latest_closed.timestamp,
                signal=Signal.SELL,
                signal_reason=eval_res.reason,
                trade_action="SELL_IGNORED_NO_POSITION",
                executed_trade=None,
                account=account,
                position=position,
                trades_count=trades_count,
                message="SELL ignorado: nenhuma posição aberta para encerrar.",
            )

        # Encerramento total da posição Spot LONG
        sell_qty = position.quantity
        gross_notional = (sell_qty * trade_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fee = (gross_notional * commission_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        net_proceeds = gross_notional - fee
        realized_pnl = net_proceeds - position.cost_basis

        new_usdt = account.usdt_balance + net_proceeds
        new_btc = Decimal("0.00000000")

        new_account = PaperAccount(
            usdt_balance=new_usdt,
            btc_balance=new_btc,
            updated_at=now_iso,
        )
        new_position = PaperPosition(
            side="NONE",
            quantity=Decimal("0.00000000"),
            cost_basis=Decimal("0.00"),
            entry_price=Decimal("0.00"),
            entry_timestamp="",
        )
        pending_trade = PaperTrade(
            id=None,
            timestamp=now_iso,
            candle_timestamp=latest_closed.timestamp,
            symbol=config.symbol,
            side="SELL",
            price=trade_price,
            quantity=sell_qty,
            notional=gross_notional,
            fee=fee,
            realized_pnl=realized_pnl,
        )

        executed_trade = storage.execute_trade_transaction(
            new_account=new_account,
            new_position=new_position,
            trade=pending_trade,
            candle_timestamp=latest_closed.timestamp,
        )

        return PaperCycleResult(
            exchange=config.exchange_id,
            symbol=config.symbol,
            timeframe=config.paper_timeframe,
            closed_candle_time=latest_closed.formatted_time,
            closed_candle_timestamp=latest_closed.timestamp,
            signal=Signal.SELL,
            signal_reason=eval_res.reason,
            trade_action="SELL_EXECUTED",
            executed_trade=executed_trade,
            account=new_account,
            position=new_position,
            trades_count=trades_count + 1,
            message="Paper SELL executado com sucesso.",
        )

    # Signal.HOLD ou sem alteração financeira
    storage.record_candle_processed(latest_closed.timestamp)
    return PaperCycleResult(
        exchange=config.exchange_id,
        symbol=config.symbol,
        timeframe=config.paper_timeframe,
        closed_candle_time=latest_closed.formatted_time,
        closed_candle_timestamp=latest_closed.timestamp,
        signal=Signal.HOLD,
        signal_reason=eval_res.reason,
        trade_action="HOLD",
        executed_trade=None,
        account=account,
        position=position,
        trades_count=trades_count,
        message="HOLD: nenhuma alteração financeira.",
    )


def format_paper_cycle_report(res: PaperCycleResult) -> str:
    """Formata o relatório textual do ciclo de Paper Trading no terminal."""
    lines = [
        "==================================================",
        "FinBot Paper Trading",
        "==================================================",
        "",
        f"Exchange: {res.exchange}",
        f"Symbol: {res.symbol}",
        f"Timeframe: {res.timeframe}",
        "",
        "Closed candle:",
        f"{res.closed_candle_time}",
        "",
    ]

    if res.trade_action == "NO_NEW_CANDLE":
        lines.extend([
            "Status:",
            "No new closed candle.",
            "",
        ])
    else:
        lines.extend([
            "Signal:",
            f"{res.signal.value}",
            "",
        ])

    if res.trade_action == "BUY_EXECUTED" and res.executed_trade:
        lines.extend([
            "Paper BUY",
            f"Price: {res.executed_trade.price:.2f} USDT",
            f"Notional: {res.executed_trade.notional:.2f} USDT",
            f"Fee: {res.executed_trade.fee:.2f} USDT",
            f"BTC acquired: {res.executed_trade.quantity:.8f} BTC",
            "",
        ])
    elif res.trade_action == "SELL_EXECUTED" and res.executed_trade:
        pnl = res.executed_trade.realized_pnl if res.executed_trade.realized_pnl is not None else Decimal("0.00")
        lines.extend([
            "Paper SELL",
            f"Price: {res.executed_trade.price:.2f} USDT",
            f"BTC sold: {res.executed_trade.quantity:.8f} BTC",
            f"Fee: {res.executed_trade.fee:.2f} USDT",
            f"Realized P/L: {pnl:+.2f} USDT",
            "",
        ])
    elif res.trade_action in ("BUY_IGNORED_POSITION_EXISTS", "SELL_IGNORED_NO_POSITION", "BUY_INSUFFICIENT_FUNDS"):
        lines.extend([
            "Action Notice:",
            f"{res.message}",
            "",
        ])

    pos_str = "NONE"
    if res.position.side == "LONG":
        pos_str = f"LONG ({res.position.quantity:.8f} BTC @ {res.position.entry_price:.2f} USDT)"

    lines.extend([
        "Paper account:",
        "",
        f"USDT: {res.account.usdt_balance:.2f}",
        f"BTC: {res.account.btc_balance:.8f}",
        "",
        "Position:",
        f"{pos_str}",
        "",
        "Trades:",
        f"{res.trades_count}",
        "",
        "Trading mode:",
        "PAPER (SIMULATION ONLY)",
        "",
        "Real trading:",
        "DISABLED",
        "",
        "No real order was sent.",
        "==================================================",
    ])
    return "\n".join(lines)


def format_paper_status_report(storage: PaperStorage, config: Config) -> str:
    """Exibe o status consolidado da conta e histórico paper sem acessar a rede."""
    account = storage.get_account()
    position = storage.get_position()
    trades_count = storage.get_trades_count()
    last_trade = storage.get_last_trade()
    last_processed = storage.get_last_processed_candle_timestamp()

    last_processed_str = "None"
    if last_processed:
        dt = datetime.fromtimestamp(last_processed / 1000, tz=timezone.utc)
        last_processed_str = f"{dt.strftime('%Y-%m-%d %H:%M:%S UTC')} ({last_processed})"

    pos_str = "NONE"
    if position.side == "LONG":
        pos_str = f"LONG ({position.quantity:.8f} BTC @ {position.entry_price:.2f} USDT, cost: {position.cost_basis:.2f} USDT)"

    last_trade_str = "None"
    if last_trade:
        pnl_str = f" | PnL: {last_trade.realized_pnl:+.2f} USDT" if last_trade.realized_pnl is not None else ""
        last_trade_str = (
            f"#{last_trade.id} {last_trade.side} {last_trade.quantity:.8f} {last_trade.symbol} "
            f"@ {last_trade.price:.2f} USDT (Fee: {last_trade.fee:.2f} USDT{pnl_str}) at {last_trade.timestamp}"
        )

    lines = [
        "==================================================",
        "FinBot Paper Trading — Status",
        "==================================================",
        "",
        "Paper account:",
        f"USDT: {account.usdt_balance:.2f}",
        f"BTC: {account.btc_balance:.8f}",
        f"Last updated: {account.updated_at}",
        "",
        "Position:",
        f"{pos_str}",
        "",
        f"Total trades: {trades_count}",
        f"Last trade: {last_trade_str}",
        f"Last processed candle: {last_processed_str}",
        "",
        f"Database: {storage.db_path}",
        "Trading mode: PAPER (SIMULATION ONLY)",
        "Real trading: DISABLED",
        "==================================================",
    ]
    return "\n".join(lines)


def main() -> None:
    """Ponto de entrada para execução de Paper Trading via CLI."""
    parser = argparse.ArgumentParser(description="FinBot Paper Trading Engine (FASE 5)")
    parser.add_argument("--status", action="store_true", help="Exibe status atual da conta e histórico paper (offline)")
    parser.add_argument("--reset", action="store_true", help="Reseta o ambiente fictício de paper trading")
    parser.add_argument("--yes", action="store_true", help="Confirmação direta para reset sem prompt interativo")
    args = parser.parse_args()

    config = get_config()
    storage = PaperStorage(db_path=config.paper_db_path)
    storage.init_db(initial_cash=Decimal(str(config.paper_initial_cash)))

    if args.status:
        report = format_paper_status_report(storage, config)
        print(report)
        return

    if args.reset:
        if not args.yes:
            confirm = input("ATENÇÃO: Confirma o reset do ambiente fictício de Paper Trading? (s/N): ").strip().lower()
            if confirm not in ("s", "sim", "y", "yes"):
                print("Operação de reset cancelada pelo usuário.")
                sys.exit(0)

        storage.reset_db(initial_cash=Decimal(str(config.paper_initial_cash)))
        print("Ambiente de Paper Trading resetado com sucesso.")
        print(f"Saldo USDT restaurado para {config.paper_initial_cash:.2f} USDT, posição zerada e histórico limpo.")
        return

    # Execução de um ciclo one-shot
    result = execute_paper_cycle(storage, config)
    report = format_paper_cycle_report(result)
    print(report)


if __name__ == "__main__":
    main()
