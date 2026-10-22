import sys
sys.path.insert(0, '/home/vmc03/norabt/nora')
import time
import numpy as np
import pandas as pd
from numba import njit, prange
from backend.data.data import read_1m

print("=" * 90, flush=True)
print("  STRESSTEST 100.000 BỘ THAM SỐ ALPHA TRÊN NẾN 1 PHÚT (1M) - DỮ LIỆU THẬT OKX BTC", flush=True)
print("=" * 90, flush=True)

# ─── BƯỚC 1: NẠP DỮ LIỆU THẬT 100% 1M TỪ CATALOG PARQUET CỦA OKX ───
t_start = time.perf_counter()
end_ms = 1791263220000
start_ms = end_ms - 365 * 86400 * 1000

print("[1/4] Đang nạp 1 năm nến 1m BTC-USDT từ OKX Parquet Catalog...", flush=True)
t0 = time.perf_counter()
raw_1m = read_1m('BTC-USDT', start_ms=start_ms, end_ms=end_ms)
t_load = (time.perf_counter() - t0) * 1000

n_1m = len(raw_1m['c'])
print(f" -> Nạp thành công: {n_1m:,} nến 1m trong {t_load:.1f}ms!", flush=True)
print(f" -> Giá BTC chạy thật: từ {raw_1m['c'][0]:,.2f} USD đến {raw_1m['c'][-1]:,.2f} USD\n", flush=True)

o_arr = raw_1m['o'].astype(np.float64)
v_arr = raw_1m['v'].astype(np.float64)
T_bars = len(o_arr)

# ─── BƯỚC 2: TÍNH TRƯỚC 10 MẢNG ALPHA #6 CHO 525,600 NẾN ───
# Alpha #6: -1 * correlation(open, volume, window)
windows = np.array([5, 8, 10, 12, 15, 20, 25, 30, 40, 50], dtype=np.int32)
buy_ths = np.linspace(0.10, 0.80, 100, dtype=np.float32)
sell_ths = np.linspace(-0.80, -0.10, 100, dtype=np.float32)

print(f"[2/4] Tính trước 10 mảng correlation (Alpha #6) trên {T_bars:,} nến 1m...", flush=True)
t0 = time.perf_counter()
df_tmp = pd.DataFrame({'open': o_arr, 'volume': v_arr})
alphas_list = []
for w in windows:
    corr = df_tmp['open'].rolling(int(w)).corr(df_tmp['volume']).fillna(0).to_numpy()
    alphas_list.append((-1.0 * corr).astype(np.float32))
t_corr = (time.perf_counter() - t0) * 1000
print(f" -> Tính xong 10 mảng Alpha (5.25 triệu giá trị) trong {t_corr:.1f}ms!\n", flush=True)

# ─── BƯỚC 3: BĂM 100.000 CẤU HÌNH SONG SONG TRÊN 16 CPU CORES ───
# 10 windows x 10,000 cặp (buy, sell) = 100,000 configs
# Chạy tối ưu cache: Mỗi window chạy 10,000 configs với alpha 1D liên tục trong RAM
N_per_w = len(buy_ths) * len(sell_ths) # 10,000
pairs_buy = np.empty(N_per_w, dtype=np.float32)
pairs_sell = np.empty(N_per_w, dtype=np.float32)

idx = 0
for b in buy_ths:
    for s in sell_ths:
        pairs_buy[idx] = b
        pairs_sell[idx] = s
        idx += 1

@njit(parallel=True, fastmath=True)
def run_window_configs(alpha_1d, o, b_arr, s_arr):
    N = len(b_arr)
    T = len(o)
    trades_out = np.zeros(N, dtype=np.int32)
    wins_out = np.zeros(N, dtype=np.int32)
    pnl_out = np.zeros(N, dtype=np.float32)
    for i in prange(N):
        b_th = b_arr[i]
        s_th = s_arr[i]
        in_pos = False
        entry_p = 0.0
        pnl_accum = 0.0
        n_trades = 0
        n_wins = 0
        for t in range(T - 1):
            val = alpha_1d[t]
            if not in_pos:
                if val > b_th:
                    in_pos = True
                    entry_p = o[t + 1]
            else:
                if val < s_th:
                    in_pos = False
                    exit_p = o[t + 1]
                    ret = (exit_p - entry_p) / entry_p
                    pnl_accum += ret
                    n_trades += 1
                    if ret > 0:
                        n_wins += 1
        trades_out[i] = n_trades
        wins_out[i] = n_wins
        pnl_out[i] = pnl_accum
    return trades_out, wins_out, pnl_out

# JIT Warmup
_ = run_window_configs(alphas_list[0][:100], o_arr[:100], pairs_buy[:2], pairs_sell[:2])

print(f"[3/4] BẮT ĐẦU STRESSTEST 100.000 CONFIGS TRÊN 525.600 NẾN 1M (52.56 TỶ EVALUATIONS)...", flush=True)
total_configs = len(windows) * N_per_w
all_windows = np.empty(total_configs, dtype=np.int32)
all_buy = np.empty(total_configs, dtype=np.float32)
all_sell = np.empty(total_configs, dtype=np.float32)
all_trades = np.empty(total_configs, dtype=np.int32)
all_wins = np.empty(total_configs, dtype=np.int32)
all_pnl = np.empty(total_configs, dtype=np.float32)

t_sweep_start = time.perf_counter()
for w_idx, w in enumerate(windows):
    t_w_start = time.perf_counter()
    w_trades, w_wins, w_pnl = run_window_configs(alphas_list[w_idx], o_arr, pairs_buy, pairs_sell)
    t_w = time.perf_counter() - t_w_start
    
    start_i = w_idx * N_per_w
    end_i = start_i + N_per_w
    all_windows[start_i:end_i] = w
    all_buy[start_i:end_i] = pairs_buy
    all_sell[start_i:end_i] = pairs_sell
    all_trades[start_i:end_i] = w_trades
    all_wins[start_i:end_i] = w_wins
    all_pnl[start_i:end_i] = w_pnl
    
    print(f" -> Window={w:2d} (10,000 configs x 525k nến): xong trong {t_w:.2f}s ({10000/t_w:,.0f} configs/s)", flush=True)

t_sweep = time.perf_counter() - t_sweep_start
rate_per_sec = total_configs / t_sweep
evals_per_sec = (total_configs * T_bars) / t_sweep

print("=" * 90, flush=True)
print(f"  ⏱️ THỜI GIAN QUÉT XONG 100.000 CONFIGS (NẾN 1M): {t_sweep:.2f} GIÂY!", flush=True)
print(f"  🚀 TỐC ĐỘ: {rate_per_sec:,.0f} CONFIGS / GIÂY", flush=True)
print(f"  ⚡ THÔNG LƯỢNG: {evals_per_sec:,.0f} BAR-EVALUATIONS / GIÂY ({evals_per_sec / 1e9:.2f} TỶ EVALUATIONS/S)", flush=True)
print("=" * 90, flush=True)

# ─── BƯỚC 4: XUẤT SHEET EXCEL & CSV ───
print("\n[4/4] Đang tổng hợp và xuất kết quả ra file Excel + CSV...", flush=True)
win_rates = np.where(all_trades > 0, (all_wins / all_trades) * 100.0, 0.0)

df_all = pd.DataFrame({
    'Window': all_windows,
    'Buy_Threshold': np.round(all_buy, 4),
    'Sell_Threshold': np.round(all_sell, 4),
    'Total_Trades': all_trades,
    'Win_Trades': all_wins,
    'Win_Rate_Pct': np.round(win_rates, 2),
    'Total_PnL_Pct': np.round(all_pnl * 100.0, 2),
})

df_all.sort_values(by=['Total_PnL_Pct', 'Win_Rate_Pct'], ascending=[False, False], inplace=True)
df_all.reset_index(drop=True, inplace=True)
df_all.index = df_all.index + 1
df_all.index.name = 'Rank'

df_top1000 = df_all.head(1000).copy()

# Summary
num_profitable = int(np.sum(all_pnl > 0))
pct_profitable = (num_profitable / total_configs) * 100.0
top1 = df_all.iloc[0]

df_summary = pd.DataFrame([
    {'Chỉ số': 'Chiến lược kiểm tra', 'Giá trị': 'WorldQuant Alpha #6 (-1 * correlation(open, volume, window))'},
    {'Chỉ số': 'Khung thời gian', 'Giá trị': '1 Năm nến 1 PHÚT (1m) THẬT từ OKX (525,600 nến)'},
    {'Chỉ số': 'Giá BTC trong kỳ', 'Giá trị': f'{raw_1m["c"][0]:,.2f} USD -> {raw_1m["c"][-1]:,.2f} USD'},
    {'Chỉ số': 'Tổng số cấu hình quét', 'Giá trị': f'{total_configs:,} cấu hình'},
    {'Chỉ số': 'Tổng số lượt tính nến', 'Giá trị': f'{total_configs * T_bars:,} lượt (52.56 tỷ lượt)'},
    {'Chỉ số': 'Thời gian nạp dữ liệu 525k nến', 'Giá trị': f'{t_load:.1f} ms'},
    {'Chỉ số': 'Thời gian tính 10 mảng Alpha', 'Giá trị': f'{t_corr:.1f} ms'},
    {'Chỉ số': 'Thời gian quét 100.000 configs', 'Giá trị': f'{t_sweep:.2f} giây'},
    {'Chỉ số': 'Tốc độ xử lý', 'Giá trị': f'{rate_per_sec:,.0f} configs / giây'},
    {'Chỉ số': 'Thông lượng tính toán', 'Giá trị': f'{evals_per_sec / 1e9:.2f} TỶ bar-evaluations / giây'},
    {'Chỉ số': 'Số config có lợi nhuận', 'Giá trị': f'{num_profitable:,} / {total_configs:,} ({pct_profitable:.1f}%)'},
    {'Chỉ số': 'Top 1 PnL cao nhất (1m)', 'Giá trị': f'+{top1["Total_PnL_Pct"]}% (Win Rate: {top1["Win_Rate_Pct"]}%)'},
    {'Chỉ số': 'Tham số Top 1', 'Giá trị': f'Window={int(top1["Window"])}, Buy>{top1["Buy_Threshold"]}, Sell<{top1["Sell_Threshold"]}'},
    {'Chỉ số': 'Tổng số lệnh Top 1', 'Giá trị': f'{int(top1["Total_Trades"]):,} lệnh ({int(top1["Win_Trades"]):,} lệnh thắng)'},
])

# Bảng so sánh Stresstest 1h vs 1m
df_compare = pd.DataFrame([
    {'Tiêu chí': 'Số lượng nến', 'Khung 1h (Lần trước)': '8,761 nến', 'Khung 1m (Stresstest)': '525,600 nến', 'Độ phóng đại': '60.0x'},
    {'Tiêu chí': 'Tổng số cấu hình', 'Khung 1h (Lần trước)': '100,000', 'Khung 1m (Stresstest)': '100,000', 'Độ phóng đại': '1.0x'},
    {'Tiêu chí': 'Tổng số phép tính nến', 'Khung 1h (Lần trước)': '876.1 triệu', 'Khung 1m (Stresstest)': '52.56 TỶ', 'Độ phóng đại': '60.0x'},
    {'Tiêu chí': 'Thời gian quét', 'Khung 1h (Lần trước)': '0.904 giây', 'Khung 1m (Stresstest)': f'{t_sweep:.2f} giây', 'Độ phóng đại': f'{t_sweep/0.904:.1f}x'},
    {'Tiêu chí': 'Tốc độ quét', 'Khung 1h (Lần trước)': '110,665 configs/s', 'Khung 1m (Stresstest)': f'{rate_per_sec:,.0f} configs/s', 'Độ phóng đại': '-'},
    {'Tiêu chí': 'Thông lượng', 'Khung 1h (Lần trước)': '0.97 tỷ ops/s', 'Khung 1m (Stresstest)': f'{evals_per_sec/1e9:.2f} tỷ ops/s', 'Độ phóng đại': f'{(evals_per_sec/1e9)/0.97:.2f}x hiệu suất SIMD'},
    {'Tiêu chí': 'Top 1 PnL', 'Khung 1h (Lần trước)': '+41.34%', 'Khung 1m (Stresstest)': f'+{top1["Total_PnL_Pct"]}%', 'Độ phóng đại': '-'},
    {'Tiêu chí': 'Số lệnh Top 1', 'Khung 1h (Lần trước)': '90 lệnh', 'Khung 1m (Stresstest)': f'{int(top1["Total_Trades"]):,} lệnh', 'Độ phóng đại': '-'},
])

# Xuất file Excel
excel_1m_path = '/home/vmc03/norabt/alpha6_100k_1m_results.xlsx'
with pd.ExcelWriter(excel_1m_path, engine='openpyxl') as writer:
    df_summary.to_excel(writer, sheet_name='Summary_1m', index=False)
    df_compare.to_excel(writer, sheet_name='Compare_1h_vs_1m', index=False)
    df_top1000.to_excel(writer, sheet_name='Top_1000_Winners_1m')

# Xuất file CSV
csv_top_1m = '/home/vmc03/norabt/alpha6_top_winners_1m.csv'
df_top1000.to_csv(csv_top_1m)

csv_all_1m = '/home/vmc03/norabt/alpha6_100k_1m_full.csv'
df_all.to_csv(csv_all_1m)

print(f"\n ĐÃ XUẤT THÀNH CÔNG BỘ DỮ LIỆU STRESSTEST NẾN 1M:")
print(f"1. Excel: {excel_1m_path}")
print(f"2. CSV Top 1,000: {csv_top_1m}")
print(f"3. CSV Full 100,000: {csv_all_1m}")
print(f"Tổng thời gian toàn bộ tiến trình (Load + Tính + Xuất): {time.perf_counter() - t_start:.2f}s\n")
