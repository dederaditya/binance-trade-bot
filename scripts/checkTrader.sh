#!/bin/bash

cmd1="sqlite3 data/crypto_trading.db"
sql0=".mode column"
sql00=".headers on"
sql1="SELECT [alt_coin_id],[alt_trade_amount],[crypto_trade_amount],datetime([datetime], '+2 hours') as TradeDateTime FROM trade_history WHERE state = 'COMPLETE' ORDER BY [datetime] DESC;"
$cmd1 "$sql0" "$sql00"  "$sql1"

sql2="SELECT datetime(MAX([datetime]), '+2 hours') AS LastTrade FROM trade_history WHERE state = 'COMPLETE';"

$cmd1 "$sql2"
