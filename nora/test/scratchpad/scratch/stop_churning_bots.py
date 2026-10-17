from backend.nautilus.live import stop_bot

for bid in ['bot_1791948928_15bf25_paper', 'bot_1791948995_e16469_paper']:
    res = stop_bot(bid, close_positions=True)
    print(f'Stopped {bid}: {res}')
