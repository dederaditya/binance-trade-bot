#!python3
import time

from .binance_api_manager import BinanceAPIManager
from .config import Config
from .database import Database
from .logger import Logger
from .scheduler import SafeScheduler
from .strategies import get_strategy
from .stats import log_progress

def main():
    config = Config()

    logger = Logger(config)
    logger.info("Starting")


    db = Database(logger, config)
    manager = BinanceAPIManager(config, db, logger)
    # check if we can access API feature that require valid config
    try:
        _ = manager.get_account()
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Couldn't access Binance API - API keys may be wrong or lack sufficient permissions")
        logger.error(e)
        return
    strategy = get_strategy(config.STRATEGY)
    if strategy is None:
        logger.error("Invalid strategy name")
        return
    trader = strategy(manager, db, logger, config)
    logger.debug(f"Chosen strategy: {config.STRATEGY}")
    logger.debug(f"Enable API: {config.ENABLE_API}")

    if config.LOSS_AFTER_HOURS > 0:
        logger.debug(f"Will allow losses after not trading for {config.LOSS_AFTER_HOURS} hours")
        logger.debug(f"Max allowed loss: {config.MAX_LOSS_PERCENT}%")
    else:
        logger.debug("Will not allow losses")

    logger.debug("Creating database schema if it doesn't already exist")
    db.create_database()
    db.set_coins(config.SUPPORTED_COIN_LIST)

    trader.initialize()

    schedule = SafeScheduler(logger)
    schedule.every(config.SCOUT_SLEEP_TIME).seconds.do(trader.scout).tag("scouting")
    schedule.every(1).minutes.do(trader.update_values).tag("updating value history")
    schedule.every(1).minutes.do(db.prune_scout_history).tag("pruning scout history")
    schedule.every(1).hours.do(db.prune_value_history).tag("pruning value history")
    schedule.every(config.LOG_PROGRESS_AFTER_HOURS).hours.do(log_progress, db=db, logger=logger).tag(
        "logging progress"
    )

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    finally:
        manager.stream_manager.close()
