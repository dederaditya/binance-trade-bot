from sqlalchemy import select
from sqlalchemy.orm import aliased

from .database import Database
from .logger import Logger
from .models import Trade, TradeState


def _get_progress_statement():
    t1 = aliased(Trade)
    t2 = aliased(Trade)

    return (
        select(
            t1.alt_coin_id.label("coin"),
            t1.alt_trade_amount.label("amount"),
            t1.crypto_trade_amount.label("priceInUSD"),
            t1.datetime.label("datetime"),
            (
                t1.alt_trade_amount
                - (
                    select(t2.alt_trade_amount)
                    .filter(
                        (t1.datetime > t2.datetime)
                        & (t2.selling == False)
                        & (t2.state == TradeState.COMPLETE)
                        & (t2.alt_coin_id == t1.alt_coin_id)
                    )
                    .limit(1)
                    .order_by(t2.datetime.desc())
                    .scalar_subquery()
                )
            ).label("change"),
        )
        .filter((t1.selling == False) & (t1.state == TradeState.COMPLETE))
        .limit(10)
        .order_by(t1.datetime.desc())
    )


def _get_progress_table(db: Database) -> str:
    with db.db_session() as session:
        progress = session.execute(_get_progress_statement())
        rows = [
            " | ".join(
                [
                    f"{t.coin:<6}",
                    f"{t.amount:>10.2f}",
                    f"{t.priceInUSD:>10.2f}",
                    f"{t.change:>10.2f}" if t.change else f"{'-- NEW! --':>10}",
                    f"{t.datetime.strftime('%Y-%m-%d %H:%M'):>16}",
                ]
            )
            for t in progress
        ]

    if len(rows) == 0:
        return "No trades."

    header = " | ".join(
        [
            f"{'Coin':<6}",
            f"{'Amount':>10}",
            f"{'USD':>10}",
            f"{'Change':>10}",
            f"{'Date/Time':<16}",
        ]
    )

    return "\n".join([header, "-" * len(rows[0]), *rows])


def log_progress(db: Database, logger: Logger):
    table = _get_progress_table(db)
    logger.info(f"Progress report for up to the last 10 trades:\n{table}")
