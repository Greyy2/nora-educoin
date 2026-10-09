#!/usr/bin/env python3
import sys
import re
import json

sys.path.insert(0, '/home/vmc03/norabt/nora')
from backend.core.strategy.pydsl.parser import compile_program

# Import original STRATEGIES
import importlib.util
spec = importlib.util.spec_from_file_location('gen50', '/home/vmc03/norabt/nora/test/scripts/generate_50_strategies.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
strategies = mod.STRATEGIES

print(f"Loaded {len(strategies)} strategies from generate_50_strategies.py")

def enrich_code(strategy):
    code = strategy['code']
    name = strategy['name']
    cat = strategy['category']
    
    # Split docstring and __algorithm__
    lines = code.split('\n')
    
    # Find def __algorithm__(self):
    algo_idx = -1
    for i, line in enumerate(lines):
        if 'def __algorithm__(self):' in line:
            algo_idx = i
            break
            
    if algo_idx == -1:
        return code
        
    pre_algo = lines[:algo_idx+1]
    body_lines = lines[algo_idx+1:]
    
    # Separate statements into 4 buckets:
    # 1. data extraction (contains self.data.)
    # 2. indicator calculation (contains self.feat. or intermediate math)
    # 3. signal triggers (contains enter or exit or crossed or & |)
    # 4. set_positions (contains self.set_positions)
    
    bucket_data = []
    bucket_feat = []
    bucket_sig = []
    bucket_pos = []
    
    for line in body_lines:
        s = line.strip()
        if not s:
            continue
        if 'self.set_positions' in s:
            bucket_pos.append(line)
        elif any(k in s for k in ['enter_', 'exit_', 'bullish_', 'bearish_', 'oversold_', 'mean_revert', 'trailing_']):
            bucket_sig.append(line)
        elif 'self.data.' in s:
            bucket_data.append(line)
        else:
            bucket_feat.append(line)
            
    # Build enriched body
    new_body = []
    
    # Step 1
    new_body.append("        # ---------------------------------------------------------------------")
    new_body.append("        # STEP 1: LOAD CAUSAL MARKET DATA")
    new_body.append("        # Extract historical price & volume series from strictly closed candles.")
    new_body.append("        # ---------------------------------------------------------------------")
    for l in bucket_data:
        new_body.append(l)
    new_body.append("")
    
    # Step 2
    new_body.append("        # ---------------------------------------------------------------------")
    new_body.append("        # STEP 2: QUANTITATIVE FEATURE & INDICATOR COMPUTATION")
    new_body.append("        # Compute mathematical signals via causal, Numba-accelerated kernels.")
    new_body.append("        # ---------------------------------------------------------------------")
    for l in bucket_feat:
        new_body.append(l)
    new_body.append("")
    
    # Step 3
    new_body.append("        # ---------------------------------------------------------------------")
    new_body.append("        # STEP 3: ALPHA LOGIC & SYSTEMATIC SIGNAL GENERATION")
    new_body.append("        # Formulate vectorized boolean masks for long entry and risk exit.")
    new_body.append("        # ---------------------------------------------------------------------")
    for l in bucket_sig:
        new_body.append(l)
    new_body.append("")
    
    # Step 4
    new_body.append("        # ---------------------------------------------------------------------")
    new_body.append("        # STEP 4: TARGET PORTFOLIO ALLOCATION & ORDER EXECUTION")
    new_body.append("        # 0.0 = Flat Cash (Risk Off) | 1.0 = 100% Long Exposure (Risk On).")
    new_body.append("        # ---------------------------------------------------------------------")
    for l in bucket_pos:
        new_body.append(l)
        
    return '\n'.join(pre_algo + new_body) + '\n'

enriched_strategies = []
all_passed = True

for idx, s in enumerate(strategies):
    new_c = enrich_code(s)
    # verify compilation
    try:
        prog = compile_program(new_c)
        print(f"[{idx+1:02d}/50] OK: {s['name']}")
        enriched_strategies.append({
            **s,
            'code': new_c
        })
    except Exception as e:
        print(f"[{idx+1:02d}/50] FAILED: {s['name']} -> {e}")
        all_passed = False

if all_passed:
    print("\nSUCCESS: All 50 enriched strategies compiled with 0 errors!")
    
    # Export to JS
    with open('/home/vmc03/norabt/nora/frontend/src/components/education/educationSamples.js', 'w', encoding='utf-8') as f:
        f.write("// Thư viện 50 Mẫu Chiến Lược Định Lượng (50 Quantitative Strategy Templates)\n")
        f.write("// Chia thành 5 danh mục kinh điển (10 mẫu/danh mục): Trend Following, Mean Reversion, Breakout, Multi-Indicator, Risk-Managed\n\n")
        f.write("export const EDU_SAMPLES = ")
        f.write(json.dumps(enriched_strategies, ensure_ascii=False, indent=2))
        f.write(";\n")
    print("Exported to frontend/src/components/education/educationSamples.js successfully!")
else:
    print("FAILED to compile enriched strategies.")
    sys.exit(1)
