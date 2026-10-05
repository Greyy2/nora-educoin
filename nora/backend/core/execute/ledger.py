"""Sổ vốn chung của một lần chạy (CapitalLedger): vốn, ký quỹ đang giữ, lãi/lỗ đã chốt."""


class CapitalLedger:
    """Sổ vốn chung của một lần chạy — nguồn sự thật duy nhất cho phân bổ vốn.

    equity   : vốn đã chốt (vốn đầu + Σ lãi/lỗ đã đóng + funding đã trả/nhận).
    reserved : tiền đang bị khoá trong các vị thế mở (ký quỹ + phí vào lệnh đã trả).
    free     : equity × usage − reserved. Mọi lệnh vào / tầng DCA phải giữ chỗ được từ free,
               nên nhiều flow cùng lúc KHÔNG thể dùng quá vốn (lỗi cũ: mỗi flow tự dùng 100%).
    """

    def __init__(self, capital: float, usage: float = 1.0):
        self.initial = float(capital)
        self.equity = float(capital)
        self.reserved = 0.0
        self.usage = max(0.0, min(float(usage), 1.0))
        self.rejected = 0  # số lần vào lệnh/tầng bị từ chối vì không đủ vốn
        self.peak = float(capital)   # đỉnh vốn ĐÃ CHỐT (cho giảm rủi ro theo mức sụt — dd_throttle_pct)

    def free(self) -> float:
        return self.equity * self.usage - self.reserved

    def reserve(self, amount: float) -> bool:
        if amount <= 0 or amount > self.free() + 1e-9:
            self.rejected += 1
            return False
        self.reserved += amount
        return True

    def release(self, amount: float) -> None:
        self.reserved = max(0.0, self.reserved - amount)

    def settle(self, cash_delta: float) -> None:
        self.equity += cash_delta
        if self.equity > self.peak:
            self.peak = self.equity
