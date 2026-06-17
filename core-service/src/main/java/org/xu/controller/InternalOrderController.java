package org.xu.controller;

import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.xu.dto.Result;
import org.xu.service.IVoucherOrderService;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/orders")
public class InternalOrderController {

    @Resource
    private IVoucherOrderService voucherOrderService;

    @GetMapping("/internal/{orderId}")
    public Result<Map<String, Object>> checkOrderStatus(@PathVariable Long orderId) {
        Map<String, Object> status = voucherOrderService.getOrderStatus(orderId);
        return Result.ok(status);
    }

    @GetMapping("/internal/user/{userId}")
    public Result<List<Map<String, Object>>> listUserOrders(
            @PathVariable Long userId,
            @RequestParam(name = "status", required = false) String status) {
        List<Map<String, Object>> orders = voucherOrderService.listUserOrders(userId, status);
        return Result.ok(orders);
    }

    @PostMapping("/internal/{orderId}/refund")
    public Result<Map<String, Object>> requestRefund(
            @PathVariable Long orderId,
            @RequestBody Map<String, Object> body) {
        String reason = body.get("reason") instanceof String s ? s : "";
        Long refundedOrderId = voucherOrderService.requestRefund(orderId, reason);
        return Result.ok(Map.of("order_id", refundedOrderId, "message", "退款申请已提交"));
    }
}
