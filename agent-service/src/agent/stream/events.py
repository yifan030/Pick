"""SSE event type constants for the Pick AI agent streaming protocol."""

# Core event types
TEXT = "text"
SHOP_CARD = "shop_card"
ERROR = "error"
DONE = "done"
STATUS = "status"
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
