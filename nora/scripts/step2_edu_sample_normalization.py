import json
from pathlib import Path

def audit_and_normalize_samples():
    samples_p = Path("nora/edu/data/alpha/education/samples.json")
    samples = json.loads(samples_p.read_text(encoding="utf-8"))

    audited = []
    for idx, s in enumerate(samples):
        # Ensure default run settings and zero-slippage disclosures
        disclosures = {
            "slippage": "Mô phỏng giả định trượt giá bằng 0. Trong giao dịch thực tế luôn có trượt giá.",
            "fees": "Phí giao dịch tính theo mặc định CEX perp (Taker 0.05%, Maker 0.02%)."
        }
        s["disclosures"] = disclosures
        if not s.get("start"):
            s["start"] = "2023-10-06"
        if not s.get("end"):
            s["end"] = "2026-10-03"
        if not s.get("initial_capital"):
            s["initial_capital"] = 10000.0
        if not s.get("train_ratio"):
            s["train_ratio"] = 0.7
        audited.append(s)

    samples_p.write_text(json.dumps(audited, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Audited and normalized {len(audited)} education samples in {samples_p}")

    # Verify 3 onboarding samples in EduStudioOnboarding.jsx
    onboarding_p = Path("nora/edu/frontend/src/components/alpha/studio/EduStudioOnboarding.jsx")
    onboarding_text = onboarding_p.read_text(encoding="utf-8")
    has_correct_sl = "stop_loss_rate = 2.0" in onboarding_text
    has_correct_tp = "take_profit_rate = 4.0" in onboarding_text
    print(f"Onboarding sample units check: SL 2.0: {has_correct_sl}, TP 4.0: {has_correct_tp}")

    # Check 3 system strategies
    strat_dir = Path("nora/edu/data/alpha/strategies")
    strat_files = sorted([f.name for f in strat_dir.glob("*.py") if not f.name.startswith("__")])
    print(f"System strategy files in strategies/: {strat_files}")

if __name__ == "__main__":
    audit_and_normalize_samples()
