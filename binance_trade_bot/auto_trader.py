from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy.orm import Session

from .binance_api_manager import BinanceAPIManager
from .config import Config
from .database import Database
from .logger import Logger
from .models import Coin, CoinValue, Pair


class AutoTrader:
    def __init__(self, binance_manager: BinanceAPIManager, database: Database, logger: Logger, config: Config):
        self.manager = binance_manager
        self.db = database
        self.logger = logger
        self.config = config

    def initialize(self):
        self.initialize_trade_thresholds()

    def transaction_through_bridge(self, pair: Pair):
        """
        Jump from the source coin to the destination coin through bridge coin
        """
        can_sell = False
        balance = self.manager.get_currency_balance(pair.from_coin.symbol)
        from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)

        if balance and balance * from_coin_price > self.manager.get_min_notional(
            pair.from_coin.symbol, self.config.BRIDGE.symbol
        ):
            can_sell = True
        else:
            # refresh balance
            self.logger.debug(f"Cached balance resulted in an invalid opportunity, refreshing balance to confirm")
            balance = self.manager.get_currency_balance(pair.from_coin.symbol, True)
            if balance and balance * from_coin_price > self.manager.get_min_notional(
                pair.from_coin.symbol, self.config.BRIDGE.symbol
            ):
                can_sell = True
            else:
                self.logger.info("Skipping sell, refreshing balances, maybe the order already went ahead?")
                self.logger.debug(f"balance={balance}")
                self.logger.debug(f"from_coin_price={from_coin_price}")
                min_notional = self.manager.get_min_notional(pair.from_coin.symbol, self.config.BRIDGE.symbol)
                self.logger.debug(f"from_symbol={pair.from_coin.symbol}")
                self.logger.debug(f"min_notional={min_notional}")

                # maybe we have a lot of usdt already?
                bridgeBalance = self.manager.get_currency_balance(self.config.BRIDGE.symbol)
                self.logger.debug(f"bridge {self.config.BRIDGE} balance {bridgeBalance}")
                if bridgeBalance < 10:
                    return None
                self.logger.info(f"Looks like there is bridge currency, will continue with buy")

        if can_sell and self.manager.sell_alt(pair.from_coin, self.config.BRIDGE) is None:
            self.logger.info("Couldn't sell, going back to scouting mode...")
            return None

        result = self.manager.buy_alt(pair.to_coin, self.config.BRIDGE)
        if result is not None:
            self.db.set_current_coin(pair.to_coin)
            self.update_trade_threshold(pair, result.price)
            return result

        self.logger.info("Couldn't buy, going back to scouting mode...")
        return None

    def update_trade_threshold(self, newPair: Pair, coin_price: float):
        """
        Update all the coins with the threshold of buying the current held coin
        """

        coin = newPair.to_coin

        if coin_price is None:
            self.logger.info("Skipping update... current coin {} not found".format(coin + self.config.BRIDGE))
            return

        session: Session
        with self.db.db_session() as session:
            inverse_pair = session.query(Pair).filter((Pair.from_coin == newPair.to_coin) & (Pair.to_coin == newPair.from_coin)).one()
            to_price = self.manager.get_ticker_price(inverse_pair.to_coin + self.config.BRIDGE)
            inverse_pair.ratio = coin_price / to_price

            for pair in session.query(Pair).filter(Pair.to_coin == coin):
                from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)

                if from_coin_price is None:
                    self.logger.info(
                        "Skipping update for coin {} not found".format(pair.from_coin + self.config.BRIDGE)
                    )
                    continue

                pair.ratio = from_coin_price / coin_price

    def initialize_trade_thresholds(self):
        """
        Initialize the buying threshold of all the coins for trading between them
        """
        session: Session
        with self.db.db_session() as session:
            for pair in session.query(Pair).filter(Pair.ratio.is_(None)).all():
                if not pair.from_coin.enabled or not pair.to_coin.enabled:
                    continue
                self.logger.debug(f"Initializing {pair.from_coin} vs {pair.to_coin}")

                from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)
                if from_coin_price is None:
                    self.logger.info(
                        "Skipping initializing {}, symbol not found".format(pair.from_coin + self.config.BRIDGE)
                    )
                    continue

                to_coin_price = self.manager.get_ticker_price(pair.to_coin + self.config.BRIDGE)
                if to_coin_price is None:
                    self.logger.info(
                        "Skipping initializing {}, symbol not found".format(pair.to_coin + self.config.BRIDGE)
                    )
                    continue

                pair.ratio = from_coin_price / to_coin_price

    def scout(self):
        """
        Scout for potential jumps from the current coin to another coin
        """
        raise NotImplementedError()

    def _get_ratios(self, coin: Coin, coin_price):
        """
        Given a coin, get the current price ratio for every other enabled coin
        """
        ratio_dict: Dict[Pair, float] = {}

        for pair in self.db.get_pairs_from(coin):
            optional_coin_price = self.manager.get_ticker_price(pair.to_coin + self.config.BRIDGE)

            if optional_coin_price is None:
                self.logger.info(
                    "Skipping scouting... optional coin {} not found".format(pair.to_coin + self.config.BRIDGE)
                )
                continue

            self.db.log_scout(pair, pair.ratio, coin_price, optional_coin_price)

            # Obtain (current coin)/(optional coin)
            coin_opt_coin_ratio = coin_price / optional_coin_price

            transaction_fee = self.manager.get_fee(pair.from_coin, self.config.BRIDGE, True) + self.manager.get_fee(
                pair.to_coin, self.config.BRIDGE, False
            )

            ratio_dict[pair] = (
                coin_opt_coin_ratio - transaction_fee * self.config.SCOUT_MULTIPLIER * coin_opt_coin_ratio
            ) - pair.ratio
        return ratio_dict

    def _jump_to_best_coin(self, coin: Coin, coin_price: float):
        """
        Given a coin, search for a coin to jump to
        """
        pair_ratios = self._get_ratios(coin, coin_price)

        # keep only ratios bigger than zero
        profitable_pairs = {k: v for k, v in pair_ratios.items() if v > 0}

        # if we have any viable options, pick the one with the biggest ratio
        if profitable_pairs:
            best_pair = max(profitable_pairs, key=profitable_pairs.get)
            self.logger.info(f"Will be jumping from {coin.symbol} to {best_pair.to_coin_id}")
            self.transaction_through_bridge(best_pair)

        if self.config.LOSS_AFTER_HOURS > 0 and self.db.get_current_coin_date() + timedelta(hours=self.config.LOSS_AFTER_HOURS) < datetime.now():
            self.logger.debug("Have been stuck for more than a day, checking if we can settle for a loss")
            max_ratio_difference = (100 - self.config.MAX_LOSS_PERCENT) / 100
            fallback_pairs = {k: v for k, v in pair_ratios.items() if ((v + k.ratio) / k.ratio) > max_ratio_difference}
            if fallback_pairs:
                best_pair = max(fallback_pairs, key=fallback_pairs.get)
                loss_estimate = (1 - ((pair_ratios[best_pair] + best_pair.ratio) / best_pair.ratio)) * 100
                self.logger.info(f"Will trade at a LOSS from {coin.symbol} to {best_pair.to_coin_id}, estimated loss {loss_estimate}%")
                self.transaction_through_bridge(best_pair)
            else:
                best_pair = max(pair_ratios, key=pair_ratios.get)
                loss_estimate = (1 - ((pair_ratios[best_pair] + best_pair.ratio) / best_pair.ratio)) * 100
                self.logger.debug(f"Loss is currently too great with pair {best_pair.to_coin_id} at {loss_estimate}%")

    def bridge_scout(self):
        """
        If we have any bridge coin leftover, buy a coin with it that we won't immediately trade out of
        """
        bridge_balance = self.manager.get_currency_balance(self.config.BRIDGE.symbol)

        for coin in self.db.get_coins():
            current_coin_price = self.manager.get_ticker_price(coin + self.config.BRIDGE)

            if current_coin_price is None:
                continue

            ratio_dict = self._get_ratios(coin, current_coin_price)
            if not any(v > 0 for v in ratio_dict.values()):
                # There will only be one coin where all the ratios are negative. When we find it, buy it if we can
                if bridge_balance > self.manager.get_min_notional(coin.symbol, self.config.BRIDGE.symbol):
                    self.logger.info(f"Will be purchasing {coin} using bridge coin")
                    self.manager.buy_alt(coin, self.config.BRIDGE)
                    return coin
        return None

    def update_values(self):
        """
        Log current value state of all altcoin balances against BTC and USDT in DB.
        """
        now = datetime.now()

        session: Session
        with self.db.db_session() as session:
            coins: List[Coin] = session.query(Coin).all()
            for coin in coins:
                balance = self.manager.get_currency_balance(coin.symbol)
                if balance == 0:
                    continue
                usd_value = self.manager.get_ticker_price(coin + "USDT")
                btc_value = self.manager.get_ticker_price(coin + "BTC")
                cv = CoinValue(coin, balance, usd_value, btc_value, datetime=now)
                session.add(cv)
                self.db.send_update(cv)
