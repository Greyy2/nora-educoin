"""AST strategy samples for Alpha Studio Builder."""
from typing import Any, Dict, List


def field(frame: str, column: str) -> Dict[str, str]:
    return {"frame": frame, "column": column, "index": "0"}


def calc(number_1: Any, logic: str, number_2: Any, multiply: float = 1.0) -> Dict[str, Any]:
    return {
        "type": "calculate",
        "number_1": number_1,
        "logic": logic,
        "number_2": number_2,
        "multiply": multiply,
    }


STRATEGY_SAMPLES: List[Dict[str, Any]] = [
    {
        "id": "keltner_long_breakout",
        "name": "Keltner Long Breakout",
        "category": "Volatility Breakout",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Mở LONG khi nến 1m phá Keltner Upper 4h; thoát khi giá xuyên lại Keltner Mid/Lower.",
        "tags": ["AST", "LONG", "Keltner", "Canonical"],
        "default_params": {
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 4.0,
            "take_profit_rate": 7.5,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "keltner_long_breakout_flow",
                "name": "LONG Keltner Breakout",
                "enabled": True,
                "ast": {
                    "type": "LONG",
                    "match": [
                        {
                            "enter_price": "touch",
                            "condition": [
                                [
                                    [field("1m", "high"), ">", field("4h", "kup17_05")],
                                    [field("4h", "atr"), ">", 0],
                                ]
                            ],
                        }
                    ],
                    "stop": [
                        {
                            "condition": [
                                [[field("1m", "low"), "<", field("4h", "kmid17_05")]],
                                [[field("1m", "close"), "<", field("4h", "klo17_05")]],
                            ]
                        }
                    ],
                },
            }
        ],
    },
    {
        "id": "keltner_short_breakdown",
        "name": "Keltner Short Breakdown",
        "category": "Volatility Breakout",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Mở SHORT khi nến 1m phá Keltner Lower 4h; thoát khi giá hồi lên Mid/Upper.",
        "tags": ["AST", "SHORT", "Keltner", "Canonical"],
        "default_params": {
            "market": "perp",  # SHORT cần perp (spot không bán khống)
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 4.0,
            "take_profit_rate": 7.5,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "keltner_short_breakdown_flow",
                "name": "SHORT Keltner Breakdown",
                "enabled": True,
                "ast": {
                    "type": "SHORT",
                    "match": [
                        {
                            "enter_price": "touch",
                            "condition": [
                                [
                                    [field("1m", "low"), "<", field("4h", "klo17_05")],
                                    [field("4h", "atr"), ">", 0],
                                ]
                            ],
                        }
                    ],
                    "stop": [
                        {
                            "condition": [
                                [[field("1m", "high"), ">", field("4h", "kmid17_05")]],
                                [[field("1m", "close"), ">", field("4h", "kup17_05")]],
                            ]
                        }
                    ],
                },
            }
        ],
    },
    {
        "id": "four_hour_range_reclaim",
        "name": "4h Range Reclaim",
        "category": "Price Action",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Mở LONG khi close 1m reclaim vùng cao 4h; thoát khi mất vùng giữa 4h.",
        "tags": ["AST", "LONG", "OHLCV"],
        "default_params": {
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 3.0,
            "take_profit_rate": 5.0,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "four_hour_range_reclaim_flow",
                "name": "LONG 4h Reclaim",
                "enabled": True,
                "ast": {
                    "type": "LONG",
                    "match": [
                        {
                            "condition": [
                                [
                                    [field("1m", "close"), ">", field("4h", "high")],
                                    [field("1m", "volume"), ">", 0],
                                ]
                            ]
                        }
                    ],
                    "stop": [
                        {
                            "condition": [
                                [[field("1m", "close"), "<", calc(field("4h", "close"), "*", 0.995)]],
                            ]
                        }
                    ],
                },
            }
        ],
    },
    {
        "id": "trend_volume_breakout",
        "name": "Trend & Volume Breakout",
        "category": "Trend Following",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Mở LONG khi 1m phá high 4h và volume 1m lớn hơn volume 4h theo tỷ lệ tương đối.",
        "tags": ["AST", "LONG", "Breakout", "Volume"],
        "default_params": {
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 3.5,
            "take_profit_rate": 6.0,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "trend_volume_breakout_flow",
                "name": "LONG Trend Volume Breakout",
                "enabled": True,
                "ast": {
                    "type": "LONG",
                    "match": [
                        {
                            "enter_price": "touch",
                            "condition": [
                                [
                                    [field("1m", "close"), ">", field("4h", "high")],
                                    [field("1m", "volume"), ">", calc(field("4h", "volume"), "*", 0.002)],
                                ]
                            ],
                        }
                    ],
                    "stop": [
                        {
                            "condition": [
                                [[field("1m", "close"), "<", field("4h", "close")]],
                            ]
                        }
                    ],
                },
            }
        ],
    },
    {
        "id": "mean_reversion_keltner",
        "name": "Mean Reversion Keltner",
        "category": "Mean Reversion",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Mở LONG khi giá xuyên dưới Keltner Lower 4h rồi thoát khi hồi về Keltner Mid 4h.",
        "tags": ["AST", "LONG", "Mean Reversion", "Keltner"],
        "default_params": {
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 5.0,
            "take_profit_rate": 4.0,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "mean_reversion_keltner_flow",
                "name": "LONG Keltner Reversion",
                "enabled": True,
                "ast": {
                    "type": "LONG",
                    "match": [
                        {
                            "enter_price": "touch",
                            "condition": [
                                [
                                    [field("1m", "low"), "<", field("4h", "klo20_15")],
                                    [field("4h", "atr"), ">", 0],
                                ]
                            ],
                        }
                    ],
                    "stop": [
                        {
                            "condition": [
                                [[field("1m", "close"), ">", field("4h", "kmid20_15")]],
                            ]
                        }
                    ],
                },
            }
        ],
    },
    {
        "id": "dual_regime_confirmation",
        "name": "Dual Regime Confirmation",
        "category": "Regime Filter",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Chỉ mở LONG khi 4h đang ở vùng lành mạnh: close trên Keltner Mid và ATR dương, rồi 1m phá high 4h.",
        "tags": ["AST", "LONG", "Regime", "Momentum"],
        "default_params": {
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 4.0,
            "take_profit_rate": 8.0,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "dual_regime_confirmation_flow",
                "name": "LONG Dual Regime",
                "enabled": True,
                "ast": {
                    "type": "LONG",
                    "match": [
                        {
                            "enter_price": "touch",
                            "condition": [
                                [
                                    [field("4h", "close"), ">", field("4h", "kmid17_05")],
                                    [field("4h", "atr"), ">", 0],
                                    [field("1m", "high"), ">", field("4h", "high")],
                                ]
                            ],
                        }
                    ],
                    "stop": [
                        {
                            "condition": [
                                [[field("4h", "close"), "<", field("4h", "kmid17_05")]],
                                [[field("1m", "close"), "<", field("4h", "close")]],
                            ]
                        }
                    ],
                },
            }
        ],
    },
    {
        "id": "two_sided_keltner_lab",
        "name": "Two-sided Keltner Lab",
        "category": "Research Workspace",
        "market": "DEX Crypto",
        "universe": "Local PKL",
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "description": "Mẫu research gồm cả LONG và SHORT để kiểm tra hai phía của kênh Keltner trong cùng một lần simulate.",
        "tags": ["AST", "LONG", "SHORT", "Keltner"],
        "default_params": {
            "market": "perp",  # SHORT cần perp (spot không bán khống)
            "initial_capital": 10000.0,
            "leverage": 1.0,
            "stop_loss_rate": 4.0,
            "take_profit_rate": 7.5,
            "using_match_price": True,
        },
        "flows": [
            {
                "id": "two_sided_long",
                "name": "LONG Keltner Upper",
                "enabled": True,
                "ast": {
                    "type": "LONG",
                    "match": [{"condition": [[[field("1m", "high"), ">", field("4h", "kup20_15")]]]}],
                    "stop": [{"condition": [[[field("1m", "low"), "<", field("4h", "kmid20_15")]]]}],
                },
            },
            {
                "id": "two_sided_short",
                "name": "SHORT Keltner Lower",
                "enabled": True,
                "ast": {
                    "type": "SHORT",
                    "match": [{"condition": [[[field("1m", "low"), "<", field("4h", "klo20_15")]]]}],
                    "stop": [{"condition": [[[field("1m", "high"), ">", field("4h", "kmid20_15")]]]}],
                },
            },
        ],
    },
]


def get_sample_by_id(sample_id: str) -> Dict[str, Any]:
    for item in STRATEGY_SAMPLES:
        if item["id"] == sample_id:
            return item
    return STRATEGY_SAMPLES[0]

# Thư viện kernel (bước 2): bắt hồi + DCA, theo xu hướng, theo đà, lướt nhanh, săn cú lớn
from backend.core.strategy.strategy_library import KERNEL_STRATEGIES  # noqa: E402

STRATEGY_SAMPLES.extend(KERNEL_STRATEGIES)
