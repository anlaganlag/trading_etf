#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fix the order of price_map computation and reconcile in gm_strategy_rolling0.py"""

# Read file in binary mode to preserve line endings
with open('gm_strategy_rolling0.py', 'rb') as f:
    content = f.read()

# Look for the actual byte pattern
idx = content.find(b'# === Reconcile Virtual vs Real ===')
if idx < 0:
    print('ERROR: Reconcile block not found')
    exit(1)

# Find the end of this block (next section "# 3. Update All Tranches")
end_marker = b'# 3. Update All Tranches'
end_idx = content.find(end_marker, idx)
if end_idx < 0:
    print('ERROR: End marker not found')
    exit(1)

# Extract the old block
old_block = content[idx:end_idx]
print(f'Found old block of {len(old_block)} bytes')
print(f'Preview: {old_block[:200]}...')

# Create new block with correct order
new_block = b'''# 2. Get Prices FIRST (needed for reconcile with market-value refund)\r
    # This ensures we only see data UP TO and INCLUDING 'today' (T day)\r
    history_until_now = context.prices_df[context.prices_df.index <= current_dt]\r
    if history_until_now.empty:\r
        return\r
    today_prices = history_until_now.iloc[-1]\r
    price_map = today_prices.to_dict()\r
\r
    # === Reconcile Virtual vs Real ===\r
    # \xe4\xbf\xae\xe5\xa4\x8d\xef\xbc\x9a\xe5\xbc\xba\xe8\xa1\x8c\xe5\xaf\xb9\xe9\xbd\x90\xe8\x99\x9a\xe6\x8b\x9f\xe5\x88\x86\xe4\xbb\x93\xe4\xb8\x8e\xe7\x9c\x9f\xe5\xae\x9e\xe6\x8c\x81\xe4\xbb\x93\xef\xbc\x8c\xe9\x98\xb2\xe6\xad\xa2\xe2\x80\x9c\xe5\xb9\xbd\xe7\x81\xb5\xe6\x8c\x81\xe4\xbb\x93\xe2\x80\x9d\xe5\xaf\xbc\xe8\x87\xb4\xe5\x90\x8e\xe7\xbb\xad\xe9\x80\xbb\xe8\xbe\x91\xe9\x94\x99\xe4\xb9\xb1\r
    # \xe4\xbd\xbf\xe7\x94\xa8\xe5\xbd\x93\xe5\x89\x8d\xe5\xb8\x82\xe4\xbb\xb7(price_map)\xe9\x80\x80\xe5\x9b\x9e\xe7\x8e\xb0\xe9\x87\x91\xef\xbc\x8c\xe9\x98\xb2\xe6\xad\xa2NAV\xe6\xb5\x81\xe5\xa4\xb1\r
    try:\r
        real_positions = {p.symbol: p.amount for p in context.account().positions()}\r
        context.rpm.reconcile_with_broker(real_positions, price_map)\r
    except Exception as e:\r
        print(f"\xe2\x9a\xa0\xef\xb8\x8f Reconcile Error: {e}")\r
\r
    '''

# Replace
content = content[:idx] + new_block + content[end_idx:]

# Write back
with open('gm_strategy_rolling0.py', 'wb') as f:
    f.write(content)

print('SUCCESS: Code block reordered and fixed')
