import json
d = json.load(open('backtest_engine_v2.json', 'r', encoding='utf-8'))
nc = d['portfolio']['nav_curve']
print(f'nav_curve entries: {len(nc)}')
for n in nc[:3]:
    print(f'  {n["date"]} nav={n["total_value"]:.0f} cash={n["cash"]:.0f} pos={n["position_value"]:.0f} open={n["open_positions"]}')
print('  ...')
for n in nc[-3:]:
    print(f'  {n["date"]} nav={n["total_value"]:.0f} cash={n["cash"]:.0f} pos={n["position_value"]:.0f} open={n["open_positions"]}')
