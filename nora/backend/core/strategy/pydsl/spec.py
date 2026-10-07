"""Đặc tả chữ ký hàm của DSL (feature / operator): tên tham số, loại, mặc định — dùng chung cho trình biên dịch (kiểm đối số, báo lỗi
có gợi ý) và cho phần tính toán.

Từ điển lý thuyết (B1): mỗi feature/operator có nhãn tiếng Việt, công thức LaTeX, giải thích ý nghĩa, cách đọc ngưỡng, số nến khởi động và nhóm phân loại.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

REQUIRED = object()

# loại tham số:
#   num   chuỗi số hoặc hằng số         bool  mặt nạ (chuỗi bool)     any  num hoặc bool
#   int   hằng số nguyên trong [lo, hi]  float hằng số trong [lo, hi]  matype hằng 0 (chỉ hỗ trợ SMA như TA-Lib mặc định)
KINDS = ("num", "bool", "any", "int", "float", "matype")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    default: Any = REQUIRED
    lo: Optional[float] = None
    hi: Optional[float] = None

    @property
    def is_series(self) -> bool:
        return self.kind in ("num", "bool", "any")


def S(name: str, default: Any = REQUIRED) -> Param:
    """Chuỗi số."""
    return Param(name, "num", default)


def B(name: str, default: Any = REQUIRED) -> Param:
    return Param(name, "bool", default)


def A(name: str, default: Any = REQUIRED) -> Param:
    return Param(name, "any", default)


def I(name: str, default: Any = REQUIRED, lo: int = 1, hi: int = 5000) -> Param:
    return Param(name, "int", default, lo, hi)


def F(name: str, default: Any = REQUIRED, lo: float = -1e9, hi: float = 1e9) -> Param:
    return Param(name, "float", default, lo, hi)


def MA(name: str) -> Param:
    return Param(name, "matype", 0)


@dataclass(frozen=True)
class Spec:
    name: str
    params: List[Param]
    fn: Callable[..., Any]
    ret: Union[str, Callable[[dict], str]] = "num"       # "num" | "bool" | hàm (đối số đã bind) -> loại
    nout: int = 1                                       # số đầu ra (tuple khi > 1)
    warm: Callable[[dict], int] = field(default=lambda p: 0)
    doc: str = ""
    label_vi: str = ""
    formula: str = ""
    meaning_vi: str = ""
    read_vi: str = ""
    warmup: Union[int, str] = 0
    category: str = ""


# ─── B1: TỪ ĐIỂN FEATURE (42 tính năng) ──────────────────────────────────────────
FEATURE_SPECS_DATA: Dict[str, Dict[str, Any]] = {
    "sma": {
        "label_vi": "Đường trung bình động giản đơn",
        "formula": r"\mathrm{SMA}_n(t) = \frac{1}{n}\sum_{i=0}^{n-1} C_{t-i}",
        "meaning_vi": "Tính mức giá trung bình số học trong n nến gần nhất, làm mượt biến động giá ngắn hạn.",
        "read_vi": "Giá cắt lên trên SMA báo hiệu xu hướng tăng, cắt xuống dưới báo hiệu xu hướng giảm.",
        "warmup": 30,
        "category": "trend",
    },
    "ema": {
        "label_vi": "Đường trung bình động hàm mũ",
        "formula": r"\mathrm{EMA}_n(t) = \alpha C_t + (1-\alpha)\mathrm{EMA}_n(t-1), \quad \alpha = \frac{2}{n+1}",
        "meaning_vi": "Tính trung bình động có trọng số mũ, ưu tiên các nến gần nhất để giảm độ trễ so với SMA.",
        "read_vi": "Phản ứng nhanh với biến động; giá duy trì trên EMA báo hiệu quán tính tăng tiếp diễn.",
        "warmup": 90,
        "category": "trend",
    },
    "dema": {
        "label_vi": "Đường trung bình động hàm mũ kép",
        "formula": r"\mathrm{DEMA}_n = 2\cdot\mathrm{EMA}_n - \mathrm{EMA}_n(\mathrm{EMA}_n)",
        "meaning_vi": "Kết hợp hai tầng EMA để triệt tiêu độ trễ pha, bám sát hành động giá.",
        "read_vi": "Nhận diện đảo chiều sớm hơn EMA thông thường; thích hợp làm đường kích hoạt tín hiệu.",
        "warmup": 180,
        "category": "trend",
    },
    "tema": {
        "label_vi": "Đường trung bình động hàm mũ ba",
        "formula": r"\mathrm{TEMA}_n = 3\cdot\mathrm{EMA} - 3\cdot\mathrm{EMA}(\mathrm{EMA}) + \mathrm{EMA}(\mathrm{EMA}(\mathrm{EMA}))",
        "meaning_vi": "Làm mượt ba tầng giúp lọc nhiễu mà vẫn giữ độ trễ cực thấp trong thị trường biến động nhanh.",
        "read_vi": "Độ nhạy rất cao với giá; phù hợp bắt nhịp bứt phá hoặc lướt sóng ngắn hạn.",
        "warmup": 270,
        "category": "trend",
    },
    "wma": {
        "label_vi": "Đường trung bình động trọng số tuyến tính",
        "formula": r"\mathrm{WMA}_n = \frac{\sum_{i=1}^n i \cdot C_{t-n+i}}{\frac{n(n+1)}{2}}",
        "meaning_vi": "Gán trọng số giảm dần theo cấp số cộng từ nến gần nhất về quá khứ.",
        "read_vi": "Ưu tiên biến động gần nhất một cách tuyến tính, nhạy hơn SMA nhưng mượt hơn giá thô.",
        "warmup": 30,
        "category": "trend",
    },
    "rsi": {
        "label_vi": "Chỉ số sức mạnh tương đối",
        "formula": r"\mathrm{RSI}_n = 100 - \frac{100}{1 + \frac{\mathrm{Wilder}(U, n)}{\mathrm{Wilder}(D, n)}}",
        "meaning_vi": "Đo lường vận tốc và biên độ dao động giá để đánh giá trạng thái hưng phấn hoặc hoảng loạn.",
        "read_vi": "RSI < 30 là vùng quá bán (tiềm năng tạo đáy), RSI > 70 là vùng quá mua (tiềm năng tạo đỉnh).",
        "warmup": 57,
        "category": "momentum",
    },
    "atr": {
        "label_vi": "Biên độ dao động thực tế trung bình",
        "formula": r"\mathrm{ATR}_n = \mathrm{Wilder}(\mathrm{TR}, n)",
        "meaning_vi": "Đo lường mức độ biến động tuyệt đối của thị trường bằng trung bình khoảng biến động n nến.",
        "read_vi": "ATR tăng mạnh thể hiện thị trường mở rộng biên độ; thường dùng để đặt khoảng dừng lỗ theo biến động.",
        "warmup": 57,
        "category": "volatility",
    },
    "natr": {
        "label_vi": "Biên độ dao động chuẩn hóa (%)",
        "formula": r"\mathrm{NATR}_n = \frac{\mathrm{ATR}_n}{C} \times 100",
        "meaning_vi": "Biểu diễn ATR dưới dạng phần trăm thị giá, giúp so sánh mức độ biến động giữa các coin khác nhau.",
        "read_vi": "NATR cao báo hiệu rủi ro dao động lớn, cần giảm đòn bẩy hoặc nới rộng khoảng cắt lỗ.",
        "warmup": 57,
        "category": "volatility",
    },
    "adx": {
        "label_vi": "Chỉ số định hướng trung bình",
        "formula": r"\mathrm{ADX}_n = \mathrm{Wilder}\left(\frac{|+\mathrm{DI} - -\mathrm{DI}|}{+\mathrm{DI} + -\mathrm{DI}} \times 100, n\right)",
        "meaning_vi": "Đo lường cường độ mạnh yếu của xu hướng giá mà không phụ thuộc vào hướng tăng hay giảm.",
        "read_vi": "ADX > 25 báo hiệu xu hướng rõ rệt và mạnh mẽ; ADX < 20 là thị trường đi ngang không xu hướng.",
        "warmup": 57,
        "category": "trend_strength",
    },
    "plus_di": {
        "label_vi": "Chỉ số định hướng dương (+DI)",
        "formula": r"+\mathrm{DI}_n = \frac{\mathrm{Wilder}(+\mathrm{DM}, n)}{\mathrm{ATR}_n} \times 100",
        "meaning_vi": "Đo áp lực và cường độ đẩy giá lên trong chu kỳ n nến.",
        "read_vi": "+DI nằm trên -DI xác nhận phe mua đang kiểm soát thị trường.",
        "warmup": 57,
        "category": "trend_strength",
    },
    "minus_di": {
        "label_vi": "Chỉ số định hướng âm (-DI)",
        "formula": r"-\mathrm{DI}_n = \frac{\mathrm{Wilder}(-\mathrm{DM}, n)}{\mathrm{ATR}_n} \times 100",
        "meaning_vi": "Đo áp lực và cường độ ép giá xuống trong chu kỳ n nến.",
        "read_vi": "-DI nằm trên +DI xác nhận phe bán đang chiếm ưu thế.",
        "warmup": 57,
        "category": "trend_strength",
    },
    "macd": {
        "label_vi": "Phân kỳ hội tụ trung bình động",
        "formula": r"\mathrm{MACD} = \mathrm{EMA}_{12} - \mathrm{EMA}_{26}, \quad \mathrm{Signal} = \mathrm{EMA}_9(\mathrm{MACD})",
        "meaning_vi": "Phát hiện sự biến chuyển động lượng và xu hướng giá qua mối tương quan giữa hai đường EMA.",
        "read_vi": "MACD cắt lên Signal là tín hiệu tăng giá; Histogram chuyển từ âm sang dương báo hiệu động lượng đảo chiều.",
        "warmup": 105,
        "category": "momentum",
    },
    "bbands": {
        "label_vi": "Dải băng Bollinger",
        "formula": r"\mathrm{Mid} = \mathrm{SMA}_n, \quad \mathrm{Upper/Lower} = \mathrm{Mid} \pm k \cdot \sigma",
        "meaning_vi": "Tạo kênh biên bao quanh giá dựa trên độ lệch chuẩn thống kê, đo độ co giãn biến động.",
        "read_vi": "Giá chạm dải dưới thể hiện vùng quá bán cục bộ; dải thắt nút cổ chai báo hiệu biến động lớn sắp tới.",
        "warmup": 5,
        "category": "volatility",
    },
    "roc": {
        "label_vi": "Tỷ lệ thay đổi phần trăm",
        "formula": r"\mathrm{ROC}_n = \frac{C_t - C_{t-n}}{C_{t-n}} \times 100",
        "meaning_vi": "Đo vận tốc biến động giá bằng phần trăm chênh lệch so với n nến trước.",
        "read_vi": "ROC > 0 thể hiện đà tăng; ROC vượt đỉnh cũ cho thấy gia tốc giá đang được đẩy mạnh.",
        "warmup": 10,
        "category": "momentum",
    },
    "rocp": {
        "label_vi": "Tỷ lệ thay đổi tương đối",
        "formula": r"\mathrm{ROCP}_n = \frac{C_t - C_{t-n}}{C_{t-n}}",
        "meaning_vi": "Tỷ lệ thay đổi giá dạng số thập phân so với n nến trước.",
        "read_vi": "Dùng tính toán động lượng tương đối dạng tỷ lệ thay vì phần trăm.",
        "warmup": 10,
        "category": "momentum",
    },
    "momentum": {
        "label_vi": "Độ chênh động lượng tuyệt đối",
        "formula": r"\mathrm{Mom}_n = C_t - C_{t-n}",
        "meaning_vi": "Hiệu số giá trị tuyệt đối giữa giá đóng cửa hiện tại và n nến trước.",
        "read_vi": "Momentum dương và tăng dần cho thấy lực đẩy giá đang mạnh lên.",
        "warmup": 10,
        "category": "momentum",
    },
    "stddev": {
        "label_vi": "Độ lệch chuẩn có trọng số",
        "formula": r"\mathrm{StdDev}_n = k \times \sqrt{\frac{1}{n}\sum (C_i - \bar{C})^2}",
        "meaning_vi": "Đo mức độ phân tán của giá quanh giá trị trung bình trong n nến.",
        "read_vi": "Độ lệch chuẩn cao nghĩa là biến động và rủi ro lớn; giá trị thấp là giai đoạn nén tích lũy.",
        "warmup": 5,
        "category": "volatility",
    },
    "var": {
        "label_vi": "Phương sai chuỗi giá",
        "formula": r"\mathrm{Var}_n = k \times \frac{1}{n}\sum (C_i - \bar{C})^2",
        "meaning_vi": "Bình phương độ lệch chuẩn, đo tổng mức biến thiên phân tán của giá.",
        "read_vi": "Phương sai tăng vọt khi thị trường có những cây nến dao động bất thường.",
        "warmup": 5,
        "category": "volatility",
    },
    "cci": {
        "label_vi": "Chỉ số kênh hàng hóa",
        "formula": r"\mathrm{CCI}_n = \frac{P_{typ} - \mathrm{SMA}(P_{typ})}{0.015 \times \mathrm{MeanDev}}",
        "meaning_vi": "So sánh mức giá điển hình với mức trung bình thống kê để phát hiện chu kỳ cực điểm.",
        "read_vi": "CCI < -100 là vùng quá bán sâu; CCI > +100 báo hiệu bứt phá bước vào xu hướng tăng mạnh.",
        "warmup": 14,
        "category": "momentum",
    },
    "willr": {
        "label_vi": "Chỉ số Williams %R",
        "formula": r"\%R_n = \frac{H_n - C}{H_n - L_n} \times (-100)",
        "meaning_vi": "Đo vị trí của giá đóng cửa so với biên độ đỉnh - đáy trong n nến gần nhất.",
        "read_vi": "%R < -80 là vùng quá bán; %R > -20 là vùng quá mua.",
        "warmup": 14,
        "category": "momentum",
    },
    "mfi": {
        "label_vi": "Chỉ số dòng tiền",
        "formula": r"\mathrm{MFI}_n = 100 - \frac{100}{1 + \frac{\text{Dòng tiền dương}}{\text{Dòng tiền âm}}}",
        "meaning_vi": "Kết hợp khối lượng và biến động giá để đo cường độ dòng tiền đổ vào hoặc rút ra khỏi thị trường.",
        "read_vi": "MFI < 20 là dòng tiền kiệt quệ (vùng quá bán); MFI > 80 là dòng tiền quá nóng (vùng quá mua).",
        "warmup": 14,
        "category": "momentum",
    },
    "obv": {
        "label_vi": "Khối lượng cân bằng lũy kế",
        "formula": r"\mathrm{OBV}_t = \mathrm{OBV}_{t-1} + \mathrm{sgn}(\Delta C) \cdot V_t",
        "meaning_vi": "Cộng dồn khối lượng vào ngày tăng và trừ đi vào ngày giảm để nhận diện dấu chân dòng tiền lớn tích lũy.",
        "read_vi": "OBV lập đỉnh mới trước giá xác nhận xu hướng tăng vững chắc từ dòng tiền thực.",
        "warmup": 1,
        "category": "volume",
    },
    "stoch": {
        "label_vi": "Dao động ngẫu nhiên Stochastic",
        "formula": r"\%K = \frac{C - L_n}{H_n - L_n} \times 100, \quad \%D = \mathrm{SMA}(\%K)",
        "meaning_vi": "So sánh giá đóng cửa với biên độ dao động cao nhất - thấp nhất trong chu kỳ.",
        "read_vi": "%K cắt lên %D tại vùng dưới 20 là điểm mua tiềm năng; cắt xuống ở trên 80 là điểm bán chốt lời.",
        "warmup": 11,
        "category": "momentum",
    },
    "donchian_upper": {
        "label_vi": "Kênh trên Donchian",
        "formula": r"\mathrm{DCH}_n = \max(H_{t-n}, \dots, H_{t-1})",
        "meaning_vi": "Đỉnh cao nhất của n nến quá khứ (không tính nến hiện tại), dùng làm ngưỡng bứt phá xu hướng.",
        "read_vi": "Giá vượt qua kênh trên Donchian là tín hiệu kích hoạt vị thế mua phá vỡ (Breakout).",
        "warmup": 20,
        "category": "channel",
    },
    "donchian_lower": {
        "label_vi": "Kênh dưới Donchian",
        "formula": r"\mathrm{DCL}_n = \min(L_{t-n}, \dots, L_{t-1})",
        "meaning_vi": "Đáy thấp nhất của n nến quá khứ (không tính nến hiện tại), dùng làm ngưỡng hỗ trợ hoặc thoát vị thế.",
        "read_vi": "Giá thủng kênh dưới Donchian kích hoạt điểm dừng lỗ hoặc tín hiệu mở short phá vỡ đáy.",
        "warmup": 20,
        "category": "channel",
    },
    "linearreg_slope": {
        "label_vi": "Độ dốc hồi quy tuyến tính",
        "formula": r"\mathrm{Slope}_n = \frac{n\sum i y_i - \sum i \sum y_i}{n\sum i^2 - (\sum i)^2}",
        "meaning_vi": "Đo độ nghiêng và hướng dốc của đường xu hướng hồi quy qua n nến.",
        "read_vi": "Độ dốc dương xác nhận giá đang trong quỹ đạo tăng; độ dốc chuyển âm báo hiệu xu hướng đảo chiều.",
        "warmup": 14,
        "category": "trend",
    },
    "linearreg": {
        "label_vi": "Đường hồi quy tuyến tính",
        "formula": r"\mathrm{LinReg}_n = a + b \cdot n",
        "meaning_vi": "Giá trị đường hồi quy tuyến tính khớp theo phương pháp bình phương tối thiểu tại nến hiện tại.",
        "read_vi": "Giá giao dịch phía trên đường hồi quy thể hiện xu thế tích cực hơn mức kỳ vọng thống kê.",
        "warmup": 14,
        "category": "trend",
    },
    "rolling_mean": {
        "label_vi": "Trung bình trượt cửa sổ n nến",
        "formula": r"\bar{X}_n = \frac{1}{n}\sum_{i=0}^{n-1} X_{t-i}",
        "meaning_vi": "Tính giá trị trung bình trượt của một chuỗi số liệu bất kỳ trong cửa sổ cố định.",
        "read_vi": "Chuỗi số liệu nằm trên giá trị trung bình phản ánh trạng thái cao hơn ngưỡng cân bằng gần đây.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_std": {
        "label_vi": "Độ lệch chuẩn trượt mẫu (ddof=1)",
        "formula": r"s_n = \sqrt{\frac{1}{n-1}\sum_{i=0}^{n-1} (X_i - \bar{X})^2}",
        "meaning_vi": "Đo lường mức độ biến động mẫu không chệch của chuỗi số liệu trong cửa sổ trượt.",
        "read_vi": "Giá trị tăng cao khi chuỗi số liệu dao động mạnh và phân tán rộng.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_max": {
        "label_vi": "Giá trị lớn nhất trượt",
        "formula": r"\max(X_t, X_{t-1}, \dots, X_{t-n+1})",
        "meaning_vi": "Tìm giá trị cực đại của chuỗi trong n nến gần nhất.",
        "read_vi": "Xác định đỉnh cục bộ hoặc mức kháng cự của chuỗi dữ liệu.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_min": {
        "label_vi": "Giá trị nhỏ nhất trượt",
        "formula": r"\min(X_t, X_{t-1}, \dots, X_{t-n+1})",
        "meaning_vi": "Tìm giá trị cực tiểu của chuỗi trong n nến gần nhất.",
        "read_vi": "Xác định đáy cục bộ hoặc mức hỗ trợ của chuỗi dữ liệu.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_sum": {
        "label_vi": "Tổng trượt n nến",
        "formula": r"\sum_{i=0}^{n-1} X_{t-i}",
        "meaning_vi": "Tính tổng tích lũy của chuỗi trong cửa sổ trượt n nến.",
        "read_vi": "Thường dùng tính tổng khối lượng, tổng biên độ hoặc số phiên thỏa mãn tiêu chí.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_zscore": {
        "label_vi": "Điểm Z-score trượt",
        "formula": r"Z_n = \frac{X_t - \bar{X}_n}{\sigma_n}",
        "meaning_vi": "Chuẩn hóa khoảng cách của giá trị hiện tại so với trung bình trượt theo số lần độ lệch chuẩn.",
        "read_vi": "Z < -2 là trạng thái lệch cực tiểu thống kê; Z > 2 là trạng thái lệch cực đại thống kê.",
        "warmup": 20,
        "category": "stats",
    },
    "zscore": {
        "label_vi": "Điểm Z-score chuẩn hóa",
        "formula": r"Z_n = \frac{X_t - \bar{X}_n}{\sigma_n}",
        "meaning_vi": "Đo độ lệch chuẩn hóa của chuỗi số so với phân phối trượt gần đây (như kernel bbz).",
        "read_vi": "Z-score vượt ra ngoài biên [-2, 2] cảnh báo trạng thái biến động dị biệt cần lưu ý.",
        "warmup": 20,
        "category": "stats",
    },
    "returns": {
        "label_vi": "Tỷ suất sinh lời đơn",
        "formula": r"R_k = \frac{X_t}{X_{t-k}} - 1",
        "meaning_vi": "Tính phần trăm tăng giảm của chuỗi giá trị sau k nến dạng số thập phân.",
        "read_vi": "Returns > 0 thể hiện chuỗi có mức sinh lời dương sau k nến.",
        "warmup": 1,
        "category": "stats",
    },
    "log_returns": {
        "label_vi": "Tỷ suất sinh lời logarit",
        "formula": r"r_k = \ln(X_t / X_{t-k})",
        "meaning_vi": "Tính tỷ suất sinh lời liên tục (log return), thuận tiện cho tính toán cộng dồn theo chuỗi thời gian.",
        "read_vi": "Chuẩn hóa phân phối lợi suất đối xứng hơn phục vụ các mô hình định lượng.",
        "warmup": 1,
        "category": "stats",
    },
    "trange": {
        "label_vi": "Khoảng biến động thực tế (True Range)",
        "formula": r"\mathrm{TR} = \max(H - L, |H - C_{-1}|, |L - C_{-1}|)",
        "meaning_vi": "Đo biên độ dao động toàn diện của nến bao gồm cả khoảng nhảy giá (gap) so với nến trước.",
        "read_vi": "Phản ánh độ biến động trung thực của từng cây nến đơn lẻ.",
        "warmup": 1,
        "category": "volatility",
    },
    "typprice": {
        "label_vi": "Giá điển hình (Typical Price)",
        "formula": r"P_{typ} = \frac{H + L + C}{3}",
        "meaning_vi": "Mức giá đại diện cho cả cây nến, tính bằng trung bình cộng giữa giá cao, thấp và đóng cửa.",
        "read_vi": "Làm mượt giá đóng cửa, hạn chế tác động của hiện tượng làm giá chốt phiên.",
        "warmup": 0,
        "category": "price",
    },
    "hlc3": {
        "label_vi": "Giá trung bình HLC3",
        "formula": r"\mathrm{HLC3} = \frac{H + L + C}{3}",
        "meaning_vi": "Đồng nghĩa với Typical Price, biểu diễn trọng tâm dao động của nến từ High, Low và Close.",
        "read_vi": "Dùng làm đầu vào tính toán thay cho giá đóng cửa để bộ lọc ổn định hơn.",
        "warmup": 0,
        "category": "price",
    },
    "ohlc4": {
        "label_vi": "Giá trung bình OHLC4",
        "formula": r"\mathrm{OHLC4} = \frac{O + H + L + C}{4}",
        "meaning_vi": "Mức giá trung bình bao quát cả 4 điểm dữ liệu cơ bản của cây nến.",
        "read_vi": "Thể hiện mức giá trung tâm thực tế của toàn bộ phiên giao dịch.",
        "warmup": 0,
        "category": "price",
    },
    "range_pct": {
        "label_vi": "Biên độ nến theo phần trăm",
        "formula": r"\text{Range\%} = \frac{H - L}{C} \times 100",
        "meaning_vi": "Tỷ lệ phần trăm chênh lệch giữa đỉnh và đáy của nến so với giá đóng cửa.",
        "read_vi": "Range% cao bất thường cảnh báo nến giằng co mạnh hoặc biến động tin tức tức thời.",
        "warmup": 0,
        "category": "volatility",
    },
    "volume_z": {
        "label_vi": "Điểm Z-score khối lượng",
        "formula": r"Z_V = \frac{V - \bar{V}_n}{\sigma_{V, n}}",
        "meaning_vi": "Đo độ đột biến của khối lượng giao dịch hiện tại so với trung bình n nến trước.",
        "read_vi": "Z_V > 2 xác nhận nến có khối lượng giao dịch đột biến cao gấp nhiều lần thông thường.",
        "warmup": 20,
        "category": "volume",
    },
}

# ─── B1: TỪ ĐIỂN OPERATOR (30 toán tử) ──────────────────────────────────────────
OP_SPECS_DATA: Dict[str, Dict[str, Any]] = {
    "crossed": {
        "label_vi": "Giao cắt hai chiều",
        "formula": r"(a > b \land a_{-1} \le b_{-1}) \lor (a < b \land a_{-1} \ge b_{-1})",
        "meaning_vi": "Phát hiện thời điểm đường a cắt đường b theo một trong hai chiều tại nến hiện tại.",
        "read_vi": "Báo hiệu khoảnh khắc giao nhau giữa hai chuỗi giá trị.",
        "warmup": 1,
        "category": "cross",
    },
    "crossed_above": {
        "label_vi": "Cắt lên trên",
        "formula": r"a > b \land a_{-1} \le b_{-1}",
        "meaning_vi": "Phát hiện thời điểm đường a cắt xuyên lên trên đường b (sự kiện theo nến).",
        "read_vi": "Tín hiệu mở vị thế MUA (LONG) hoặc thoát vị thế BÁN (SHORT).",
        "warmup": 1,
        "category": "cross",
    },
    "crossed_below": {
        "label_vi": "Cắt xuống dưới",
        "formula": r"a < b \land a_{-1} \ge b_{-1}",
        "meaning_vi": "Phát hiện thời điểm đường a cắt xuyên xuống dưới đường b (sự kiện theo nến).",
        "read_vi": "Tín hiệu mở vị thế BÁN (SHORT) hoặc thoát vị thế MUA (LONG).",
        "warmup": 1,
        "category": "cross",
    },
    "current": {
        "label_vi": "Giá trị nến hiện tại",
        "formula": r"x_t",
        "meaning_vi": "Lấy giá trị của chuỗi tại đúng cây nến hiện tại (phép toán đồng nhất).",
        "read_vi": "Đại diện cho trạng thái thời điểm t tức thời.",
        "warmup": 0,
        "category": "shift",
    },
    "previous": {
        "label_vi": "Giá trị nến trước",
        "formula": r"x_{t-k}, \quad k \ge 1",
        "meaning_vi": "Lấy giá trị của chuỗi lùi về quá khứ k nến, tuân thủ nghiêm ngặt tính nhân quả.",
        "read_vi": "Dùng để so sánh giá trị hiện tại với trạng thái quá khứ.",
        "warmup": 1,
        "category": "shift",
    },
    "shift": {
        "label_vi": "Dịch chuyển chuỗi về quá khứ",
        "formula": r"\mathrm{Lag}_k(x) = x_{t-k}",
        "meaning_vi": "Dịch chuyển toàn bộ chuỗi dữ liệu lùi lại k bước nến để tránh thiên lệch tương lai.",
        "read_vi": "Đảm bảo tín hiệu chỉ sử dụng thông tin đã đóng nến trong quá khứ.",
        "warmup": 1,
        "category": "shift",
    },
    "diff": {
        "label_vi": "Chênh lệch tuyệt đối",
        "formula": r"\Delta x = x_t - x_{t-k}",
        "meaning_vi": "Tính hiệu số giữa giá trị hiện tại và giá trị k nến trước đó.",
        "read_vi": "Diff > 0 thể hiện giá trị đang tăng lên so với nến quá khứ.",
        "warmup": 1,
        "category": "change",
    },
    "pct_change": {
        "label_vi": "Phần trăm thay đổi",
        "formula": r"\frac{x_t - x_{t-k}}{x_{t-k}}",
        "meaning_vi": "Tính tốc độ thay đổi tương đối của chuỗi sau k nến.",
        "read_vi": "Giá trị dương là chuỗi đang tăng trưởng, giá trị âm là chuỗi đang sụt giảm.",
        "warmup": 1,
        "category": "change",
    },
    "rising": {
        "label_vi": "Tăng liên tục k nến",
        "formula": r"x_t > x_{t-1} > \dots > x_{t-k}",
        "meaning_vi": "Kiểm tra chuỗi số có tăng đơn điệu liên tục qua k nến liên tiếp hay không.",
        "read_vi": "Xác nhận quán tính tăng giá dốc và bền bỉ, không bị đứt đoạn.",
        "warmup": 1,
        "category": "change",
    },
    "falling": {
        "label_vi": "Giảm liên tục k nến",
        "formula": r"x_t < x_{t-1} < \dots < x_{t-k}",
        "meaning_vi": "Kiểm tra chuỗi số có giảm đơn điệu liên tục qua k nến liên tiếp hay không.",
        "read_vi": "Xác nhận quán tính giảm giá dốc và liên tục.",
        "warmup": 1,
        "category": "change",
    },
    "fillna": {
        "label_vi": "Điền giá trị rỗng",
        "formula": r"\begin{cases} x_t & \text{nếu } x_t \ne \mathrm{NaN} \\ v & \text{ngược lại} \end{cases}",
        "meaning_vi": "Thay thế các điểm dữ liệu rỗng (NaN) bằng một hằng số xác định.",
        "read_vi": "Làm sạch dữ liệu khởi động hoặc các điểm khuyết thiếu.",
        "warmup": 0,
        "category": "clean",
    },
    "ffill": {
        "label_vi": "Điền giá trị hợp lệ gần nhất",
        "formula": r"x_t = x_{t-1} \text{ khi } x_t \text{ là NaN}",
        "meaning_vi": "Kéo dài giá trị hợp lệ gần nhất trong quá khứ để lấp đầy các khoảng NaN.",
        "read_vi": "Bảo toàn trạng thái cuối cùng được kích hoạt.",
        "warmup": 0,
        "category": "clean",
    },
    "abs": {
        "label_vi": "Giá trị tuyệt đối",
        "formula": r"|x_t|",
        "meaning_vi": "Lấy độ lớn tuyệt đối của chuỗi số, loại bỏ dấu âm.",
        "read_vi": "Đo quy mô biến động không phân biệt chiều hướng.",
        "warmup": 0,
        "category": "math",
    },
    "clip": {
        "label_vi": "Kẹp biên giới hạn",
        "formula": r"\min(\max(x_t, \text{lower}), \text{upper})",
        "meaning_vi": "Giới hạn giá trị của chuỗi nằm gọn trong khoảng [lower, upper].",
        "read_vi": "Triệt tiêu các điểm cực trị dị biệt làm sai lệch mô hình định lượng.",
        "warmup": 0,
        "category": "clean",
    },
    "isna": {
        "label_vi": "Kiểm tra giá trị rỗng",
        "formula": r"x_t = \mathrm{NaN}",
        "meaning_vi": "Trả về True nếu điểm dữ liệu là NaN (chưa đủ nến khởi động hoặc thiếu dữ liệu).",
        "read_vi": "Dùng để kiểm soát tính khả dụng trước khi thực thi logic.",
        "warmup": 0,
        "category": "check",
    },
    "notna": {
        "label_vi": "Kiểm tra có dữ liệu",
        "formula": r"x_t \ne \mathrm{NaN}",
        "meaning_vi": "Trả về True nếu điểm dữ liệu hợp lệ và không bị rỗng.",
        "read_vi": "Xác nhận chuỗi đã qua giai đoạn khởi động an toàn.",
        "warmup": 0,
        "category": "check",
    },
    "isfinite": {
        "label_vi": "Kiểm tra giá trị hữu hạn",
        "formula": r"|x_t| < \infty \land x_t \ne \mathrm{NaN}",
        "meaning_vi": "Kiểm tra số liệu không bị chia cho 0 hoặc lỗi tràn số vô cực.",
        "read_vi": "Lọc bỏ các giá trị vô cực bất thường trước khi so sánh.",
        "warmup": 0,
        "category": "check",
    },
    "zero_ifna": {
        "label_vi": "Gán 0 nếu rỗng",
        "formula": r"\begin{cases} x_t & \text{nếu hợp lệ} \\ 0 & \text{nếu NaN} \end{cases}",
        "meaning_vi": "Quy đổi mọi giá trị NaN hoặc không xác định về mức 0.",
        "read_vi": "Đảm bảo phép cộng trừ chuỗi không bị gián đoạn bởi NaN.",
        "warmup": 0,
        "category": "clean",
    },
    "sign": {
        "label_vi": "Dấu của số liệu",
        "formula": r"\mathrm{sgn}(x_t) \in \{-1, 0, 1\}",
        "meaning_vi": "Xác định hướng của số liệu: 1 nếu dương, -1 nếu âm, 0 nếu bằng 0.",
        "read_vi": "Xác định chiều hướng vị thế hoặc biến động độc lập với quy mô.",
        "warmup": 0,
        "category": "math",
    },
    "replace": {
        "label_vi": "Thay thế giá trị cụ thể",
        "formula": r"\begin{cases} v & \text{nếu } x_t = \text{target} \\ x_t & \text{ngược lại} \end{cases}",
        "meaning_vi": "Thay thế một giá trị mục tiêu cụ thể bằng một giá trị mới.",
        "read_vi": "Hiệu chỉnh các mã lỗi hoặc giá trị quy ước đặc thù.",
        "warmup": 0,
        "category": "clean",
    },
    "between": {
        "label_vi": "Nằm trong khoảng biên",
        "formula": r"\text{lower} \le x_t \le \text{upper}",
        "meaning_vi": "Kiểm tra chuỗi số liệu có nằm trong khoảng giới hạn hai đầu hay không.",
        "read_vi": "Xác định điều kiện dao động trong biên an toàn (ví dụ: RSI từ 40 đến 60).",
        "warmup": 0,
        "category": "check",
    },
    "where": {
        "label_vi": "Lựa chọn theo điều kiện",
        "formula": r"\text{cond} \;?\; a : b",
        "meaning_vi": "Chọn giá trị a nếu điều kiện cond đúng, ngược lại chọn giá trị b.",
        "read_vi": "Rẽ nhánh logic chỉ báo hoặc giá trị vị thế linh hoạt theo nến.",
        "warmup": 0,
        "category": "conditional",
    },
    "value_when": {
        "label_vi": "Giá trị tại lần thỏa điều kiện gần nhất",
        "formula": r"x_{\tau}, \quad \tau = \max \{i \le t \mid \text{cond}_i = \mathrm{True}\}",
        "meaning_vi": "Lưu giữ giá trị x tại cây nến gần nhất mà điều kiện cond xảy ra.",
        "read_vi": "Dùng ghi nhớ mức giá vào lệnh hoặc đỉnh/đáy gần nhất làm mốc đối chiếu.",
        "warmup": 0,
        "category": "conditional",
    },
    "bars_since": {
        "label_vi": "Số nến kể từ lần thỏa điều kiện gần nhất",
        "formula": r"t - \max \{i \le t \mid \text{cond}_i = \mathrm{True}\}",
        "meaning_vi": "Đếm số cây nến trôi qua kể từ lần gần nhất điều kiện cond được thỏa mãn (0 = ngay nến này).",
        "read_vi": "Dùng kiểm soát thời gian nắm giữ, timeout thoát vị thế hoặc chu kỳ làm nguội.",
        "warmup": 0,
        "category": "conditional",
    },
    "hold_for": {
        "label_vi": "Duy trì trạng thái qua k nến",
        "formula": r"\exists i \in [t-k+1, t]: \text{cond}_i = \mathrm{True}",
        "meaning_vi": "Kéo dài hiệu lực của điều kiện True trong k nến liên tiếp kể từ lần xuất hiện gần nhất.",
        "read_vi": "Giữ trạng thái bật tín hiệu đủ lâu để chờ nến xác nhận tiếp theo.",
        "warmup": 1,
        "category": "conditional",
    },
    "crossed_above_value": {
        "label_vi": "Cắt lên trên ngưỡng hằng số",
        "formula": r"a_t > v \land a_{t-1} \le v",
        "meaning_vi": "Phát hiện thời điểm đường a cắt vượt lên một mốc số cố định (ví dụ RSI cắt lên 30).",
        "read_vi": "Tín hiệu bứt phá thoát khỏi vùng quá bán hoặc vượt mốc cản ngang.",
        "warmup": 1,
        "category": "cross",
    },
    "crossed_below_value": {
        "label_vi": "Cắt xuống dưới ngưỡng hằng số",
        "formula": r"a_t < v \land a_{t-1} \ge v",
        "meaning_vi": "Phát hiện thời điểm đường a cắt xuyên xuống dưới một mốc số cố định (ví dụ RSI cắt xuống 70).",
        "read_vi": "Tín hiệu thoái lui khỏi vùng quá mua hoặc thủng ngưỡng hỗ trợ ngang.",
        "warmup": 1,
        "category": "cross",
    },
    "and_": {
        "label_vi": "Điều kiện VÀ logic",
        "formula": r"a \land b",
        "meaning_vi": "Cả hai điều kiện a và b phải đồng thời thỏa mãn tại cùng một cây nến.",
        "read_vi": "Dùng kết hợp nhiều bộ lọc tín hiệu (ví dụ: xu hướng tăng VÀ động lượng quá bán).",
        "warmup": 0,
        "category": "logic",
    },
    "or_": {
        "label_vi": "Điều kiện HOẶC logic",
        "formula": r"a \lor b",
        "meaning_vi": "Ít nhất một trong hai điều kiện a hoặc b thỏa mãn tại cây nến.",
        "read_vi": "Dùng cho các điều kiện thoát vị thế đa dạng (ví dụ: chạm SL HOẶC tín hiệu đảo chiều).",
        "warmup": 0,
        "category": "logic",
    },
    "not_": {
        "label_vi": "Điều kiện PHỦ ĐỊNH logic",
        "formula": r"\neg a",
        "meaning_vi": "Đảo ngược trạng thái logic của điều kiện a (True thành False và ngược lại).",
        "read_vi": "Dùng để loại trừ các trường hợp cấm vào lệnh.",
        "warmup": 0,
        "category": "logic",
    },
}
