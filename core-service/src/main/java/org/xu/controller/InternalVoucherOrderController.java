package org.xu.controller;

import jakarta.annotation.Resource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.xu.dto.Result;
import org.xu.service.IVoucherOrderService;

import java.util.Map;

@RestController
@RequestMapping("/api/voucher-order")
public class InternalVoucherOrderController {

    @Resource
    private IVoucherOrderService voucherOrderService;

    @Value("${sync.internal-token}")
    private String internalToken;

    private void checkToken(String token) {
        if (token == null || !token.equals(internalToken)) {
            throw new RuntimeException("Unauthorized");
        }
    }

    @PostMapping("/internal/{voucherId}")
    public Result<Map<String, Object>> internalPlaceOrder(
            @PathVariable Long voucherId,
            @RequestBody Map<String, Object> body,
            @RequestHeader("X-Internal-Token") String token) {
        checkToken(token);

        Long userId = body.get("user_id") instanceof Number n ? n.longValue() : null;
        int quantity = body.get("quantity") instanceof Number n ? n.intValue() : 1;

        if (userId == null) {
            return Result.fail("user_id is required");
        }

        try {
            Long orderId = voucherOrderService.createOrderInternal(voucherId, userId, quantity);
            return Result.ok(Map.of("order_id", orderId, "message", "下单成功"));
        } catch (Exception e) {
            return Result.fail(e.getMessage());
        }
    }
}
