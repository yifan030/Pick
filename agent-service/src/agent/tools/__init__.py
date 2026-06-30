"""Agent tools for the Pick AI Shopping Guide.

Tools by domain:
- recommendation/search_shops: Dual-collection RAG retrieval
- commerce/query_vouchers: Query available vouchers from Java backend
- commerce/place_order: Place a voucher order (triggers HumanInTheLoopMiddleware)
- memory_tools: Memory management (view/delete/update/clear preferences)
"""

from src.agent.tools.recommendation.search_shops import search_shops
from src.agent.tools.commerce.query_vouchers import query_vouchers
from src.agent.tools.commerce.place_order import place_order
from src.agent.tools.commerce.check_orders import check_order_status, list_my_orders
from src.agent.tools.commerce.request_refund import request_refund
from src.agent.tools.social.bookmarks import bookmark_shop, list_bookmarks, remove_bookmark
from src.agent.tools.social.alerts import set_voucher_alert
from src.agent.tools.store.reservation import queue_reservation, make_reservation
from src.agent.tools.memory_tools import create_memory_tools

__all__ = [
    "search_shops",
    "query_vouchers",
    "place_order",
    "check_order_status",
    "list_my_orders",
    "request_refund",
    "bookmark_shop",
    "list_bookmarks",
    "remove_bookmark",
    "set_voucher_alert",
    "queue_reservation",
    "make_reservation",
    "create_memory_tools",
]
