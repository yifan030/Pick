"""Kafka 消费者链路就绪前的降级方案。

在下一轮对话的 Profile Updater 中从对话上下文自然感知反馈：
如用户说"上次那家太贵了"→ implicit rejection，
不依赖独立事件链路。
"""


def detect_implicit_feedback(user_message: str) -> list[dict]:
    """从用户消息中检测隐式反馈信号。

    Args:
        user_message: 用户本轮消息文本

    Returns:
        list of {"type": "rejection"|"appreciation"|"correction", "detail": str}
    """
    signals = []

    # 隐式拒绝信号
    rejection_patterns = [
        ("太贵了", "budget_too_high"),
        ("太远了", "distance_too_far"),
        ("不喜欢那家", "dislike_shop"),
        ("上次推荐的不好", "bad_recommendation"),
        ("换一家", "want_alternative"),
        ("不好吃", "bad_taste"),
        ("不划算", "not_worth_it"),
        ("太辣了", "too_spicy"),
    ]
    for pattern, detail in rejection_patterns:
        if pattern in user_message:
            signals.append({"type": "rejection", "detail": detail})

    # 隐式满意信号
    appreciation_patterns = [
        ("还不错", "moderate_satisfaction"),
        ("挺好的", "good_satisfaction"),
        ("就去那家吧", "decision_confirmed"),
        ("上次那家好吃", "previous_good"),
        ("推荐得不错", "recommendation_good"),
        ("很满意", "very_satisfied"),
    ]
    for pattern, detail in appreciation_patterns:
        if pattern in user_message:
            signals.append({"type": "appreciation", "detail": detail})

    # 纠错信号
    correction_patterns = [
        ("错了", "explicit_correction"),
        ("不对", "explicit_correction"),
        ("其实是", "implicit_correction"),
        ("应该是", "implicit_correction"),
    ]
    for pattern, detail in correction_patterns:
        if pattern in user_message:
            signals.append({"type": "correction", "detail": detail})

    return signals
