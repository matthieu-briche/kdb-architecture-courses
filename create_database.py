from datetime import time
from glob import glob
import os
import shutil
import pykx as kx
import pandas as pd

# Check if database exists, if it does, remove it
directory = "./database"

# Check if the directory exists and remove it
if os.path.exists(directory):
    # Delete the directory and all its contents
    shutil.rmtree(directory)
    #make a new database directory
    os.mkdir(directory) 
    
# Define Schemas
trade = kx.schema.builder({
    'time': kx.TimespanAtom, 'sym': kx.SymbolAtom,
    'exchange': kx.SymbolAtom, 'sz': kx.LongAtom,
    'px': kx.FloatAtom})

quote = kx.schema.builder({
    'time': kx.TimespanAtom, 'sym': kx.SymbolAtom,
    'exchange': kx.SymbolAtom, 'bid': kx.FloatAtom,
    'ask': kx.FloatAtom, 'bidsz': kx.LongAtom,
    'asksz': kx.LongAtom})

## Create 10 days of historic trade and quote data
days = 10
num_trades=10000
num_quotes = round(num_trades/3)
symlist = ['AAPL', 'JPM', 'GOOG', 'BRK', 'WPO', 'IBM']
exlist = ['NYSE', 'LON', 'CHI', 'HK']

db = kx.DB(path='database')

gzip = kx.Compress(algo=kx.CompressionAlgorithm.gzip, level=8)

while days>0:
    # Generate random trade data
    trade_data = [
        kx.q.asc(kx.random.random(num_trades, kx.q('1D00:00:00.000'))),
        kx.random.random(num_trades, symlist),
        kx.random.random(num_trades, exlist),
        10*kx.random.random(num_trades, 100),
        20+kx.random.random(num_trades, 100.0)]

    # Generate random quote data
    ask = kx.random.random(num_quotes, 100.0)
    asksz = 10*kx.random.random(num_quotes, 100)
    bd = ask - kx.random.random(num_quotes, ask)
    bdsz = asksz - kx.random.random(num_quotes, asksz)
    quote_data = [
        kx.q.asc(kx.random.random(num_quotes, kx.q('1D'))),
        kx.random.random(num_quotes, symlist),
        kx.random.random(num_quotes, exlist),
        bd,
        ask,
        bdsz,
        asksz]

    # Generate trade and quote database partitions
    db.create(trade.insert(trade_data, inplace=False), 'trade', kx.DateAtom('today') - days, compress=gzip)
    db.create(quote.insert(quote_data, inplace=False), 'quote', kx.DateAtom('today') - days, compress=gzip)

    # Decrement the number of days that need to be supplied
    days -= 1
    
    # Display tardes and quotes tables


# Extraire les tables sous forme de DataFrame Pandas
df_trade = kx.q('select from trade').pd()
df_quote = kx.q('select from quote').pd()

# Afficher les 5 premières lignes
print("--- TABLE TRADE ---")
print(df_trade.head())

print("\n--- TABLE QUOTE ---")
print(df_quote.head())