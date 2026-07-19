#!/usr/bin/env python3
"""
示例：計算 TTM PE 和 Forward PE

展示 compute_trailing_pe() 和 compute_forward_pe() 的使用方式。
"""

from signal_engine import compute_trailing_pe, compute_forward_pe

# 示例數據：近 8 季 EPS
quarterly_data = {
    (2026, 2): {"eps": 14.0},  # 最新一季
    (2026, 1): {"eps": 13.5},
    (2025, 4): {"eps": 13.0},
    (2025, 3): {"eps": 12.5},  # 過去 4 季小計：53.0
    (2025, 2): {"eps": 12.0},  # 更早 4 季
    (2025, 1): {"eps": 11.5},
    (2024, 4): {"eps": 11.0},
    (2024, 3): {"eps": 10.5},  # 更早 4 季小計：45.0
}

# 當前股價
current_price = 2470.0

# 計算 TTM PE
ttm_pe = compute_trailing_pe(current_price, quarterly_data)
print(f"📊 TTM PE 計算結果")
print(f"  股價: ${current_price:.2f}")
print(f"  近四季 EPS 合計: 53.0")
print(f"  TTM PE = {current_price} / 53.0 = {ttm_pe:.2f}x")
print()

# 計算 Forward PE
forward_pe = compute_forward_pe(current_price, quarterly_data)
print(f"📊 Forward PE 計算結果")
print(f"  股價: ${current_price:.2f}")
print(f"  計算方法: 基於近 4 季 (53.0) vs 更早 4 季 (45.0) 推估增長率")
growth_rate = (53.0 / (45.0 / 1)) - 1  # 近 4 季 vs 更早平均
print(f"  推估增長率: ~{growth_rate:.1%}")
print(f"  前瞻年化 EPS ≈ 53.0 × (1 + growth_rate) = 預期未來 12 個月 EPS")
print(f"  Forward PE = {current_price} / 前瞻EPS ≈ {forward_pe:.2f}x")
print()

# 估值解讀
pe_diff = ttm_pe - forward_pe
print(f"💡 估值對比")
print(f"  TTM PE vs Forward PE: {ttm_pe:.2f}x vs {forward_pe:.2f}x (差異: {pe_diff:.2f}x)")
if pe_diff > 0:
    print(f"  → TTM PE > Forward PE：市場預期未來 EPS 會上升（樂觀）")
else:
    print(f"  → TTM PE < Forward PE：市場預期未來 EPS 會下降（保守）")
print()

# 邊界情況
print(f"⚠️ 邊界情況展示")
print(f"  1. 只有 2 季數據時的 Forward PE 計算:")
limited_data = {
    (2026, 2): {"eps": 14.0},
    (2026, 1): {"eps": 13.5},
}
limited_forward_pe = compute_forward_pe(2470.0, limited_data)
print(f"     Forward PE = {2470.0} / (14.0 × 4) = {limited_forward_pe:.2f}x")
print(f"  2. 無有效 EPS 數據時:")
print(f"     Forward PE = {compute_forward_pe(2470.0, {})} (回傳 0)")
