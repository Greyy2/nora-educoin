import json

with open("nora/coin/data/alpha/research/okx_top10_agents.json") as f:
    d = json.load(f)

bots = d.get("bots", [])
print(f"Tổng số bot OKX: {len(bots)}")

for b in bots[:3]:
    print("\n==========================================")
    print(f"Bot Slug: {b.get('slug')}")
    print(f"Name: {b.get('name')}")
    print(f"Class: {b.get('bot_class')}")
    print(f"Formula summary: {b.get('formula_summary')}")
    print(f"Exit structure: {b.get('exit_structure')}")
    print(f"Report stats: {b.get('report_stats')}")
    print(f"Implied exit fit: {b.get('implied_exit_fit')}")
