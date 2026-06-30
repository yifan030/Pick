"""SSE event type constants and helpers for the Pick AI agent streaming protocol."""

import time
import uuid

# Core event types
TEXT = "text"
SHOP_CARD = "shop_card"
ERROR = "error"
DONE = "done"
STATUS = "status"
# -- Feedback Tracking Helpers ------------------------------------------------


def generate_trace_id() -> str:
    """Generate a unique trace_id for recommendation tracking."""
    return f"trace_rec_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def build_shop_card_event(
    shop: dict,
    trace_id: str = "",
    referenced_profiles: list | None = None,
) -> dict:
    """Build a shop_card SSE event dict with feedback tracking fields.

    Args:
        shop: The shop data dict to include in the event.
        trace_id: Optional trace_id for feedback tracking.
                  Auto-generated if not provided.
        referenced_profiles: Optional list of Profile atom IDs that
                             contributed to this recommendation.

    Returns:
        An SSE event dict ready for JSON serialization.
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
