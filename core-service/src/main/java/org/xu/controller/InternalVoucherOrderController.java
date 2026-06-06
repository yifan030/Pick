package org.xu.controller;

import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.xu.dto.Result;
import org.xu.entity.SeckillVoucher;
import org.xu.service.ISeckillVoucherService;
import org.xu.service.IVoucherOrderService;

import java.util.Map;

@RestController
@RequestMapping("/api/voucher-order")
public class InternalVoucherOrderController {

    @Resource
    private IVoucherOrderService voucherOrderService;

    @Resource
    private ISeckillVoucherService seckillVoucherService;

    @PostMapping("/internal/{voucherId}")
    public Result<Map<String, Object>> internalPlaceOrder(
            @PathVariable Long voucherId,
            @RequestBody Map<String, Object> body) {

        Long userId = body.get("user_id") instanceof Number n ? n.longValue() : null;
        int quantity = body.get("quantity") instanceof Number n ? n.intValue() : 1;

        if (userId == null) {
            return Result.fail("user_id is required");
        }

        // 秒杀券拦截：秒杀券不支持代下单
        SeckillVoucher seckill = seckillVoucherService.lambdaQuery()
                .eq(SeckillVoucher::getVoucherId, voucherId).one();
        if (seckill != null) {
            return Result.fail("SECKILL_NOT_SUPPORTED:秒杀券暂不支持自动下单，请留意秒杀开始时间手动参与");
        }

        try {
            Long orderId = voucherOrderService.createOrderInternal(voucherId, userId, quantity);
            return Result.ok(Map.of("order_id", orderId, "message", "下单成功"));
        } catch (Exception e) {
            return Result.fail(e.getMessage());
        }
    }
}
