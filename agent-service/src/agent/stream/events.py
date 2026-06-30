"""SSE event type constants for the Pick AI agent streaming protocol."""

import time
import uuid

# Core event types
TEXT = "text"
SHOP_CARD = "shop_card"
ERROR = "error"
DONE = "done"
STATUS = "status"


def generate_trace_id() -> str:
    """Generate a unique trace_id for recommendation tracking.

    Format: trace_rec_{unix_timestamp}_{8_hex_chars}
    Used by the feedback loop to reverse-lookup which Profile atoms
    were referenced when a recommendation was made.
    """
    return f"trace_rec_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def build_shop_card_event(
    shop: dict,
    trace_id: str = "",
    referenced_profiles: list[str] | None = None,
) -> dict:
    """Build a shop_card SSE event dict with feedback tracking fields.

    Args:
        shop: Full shop data dict from search results.
        trace_id: Recommendation trace ID for feedback loop. Auto-generated if empty.
        referenced_profiles: List of Profile atom IDs used for this recommendation.

    Returns:
        Dict ready for SSE emission with type, shop, trace_id, referenced_profiles.
    """
    return {
        "type": "shop_card",
        "shop": shop,
        "trace_id": trace_id or generate_trace_id(),
        "referenced_profiles": referenced_profiles or [],
    }
# Iteration 2: Order lifecycle
ORDER_STATUS = "order_status"
ORDER_LIST = "order_list"
REFUND_STATUS = "refund_status"
# Iteration 3: Bookmarks & Alerts
BOOKMARK_ADDED = "bookmark_added"
BOOKMARK_REMOVED = "bookmark_removed"
ALERT_SET = "alert_set"
# Iteration 4: In-store
RESERVATION_MADE = "reservation_made"
QUEUE_JOINED = "queue_joined"
NAVIGATION_INFO = "navigation_info"
