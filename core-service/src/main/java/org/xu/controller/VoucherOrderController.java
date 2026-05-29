package org.xu.controller;


import jakarta.annotation.Resource;
import jakarta.validation.Valid;
import org.xu.dto.CancelVoucherOrderDto;
import org.xu.dto.GetVoucherOrderByVoucherIdDto;
import org.xu.dto.GetVoucherOrderDto;
import org.xu.dto.Result;
import org.xu.execute.RateLimitHandler;
import org.xu.ratelimit.extension.RateLimitScene;
import org.xu.service.IReconciliationTaskService;
import org.xu.service.ISeckillAccessTokenService;
import org.xu.service.IVoucherOrderService;
import org.xu.utils.UserHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;


/**
 
 * @description: 优惠券订单api

 **/
@RestController
@RequestMapping("/voucher-order")
public class VoucherOrderController {

    @Resource
    private IVoucherOrderService voucherOrderService;

    @Resource
    private ISeckillAccessTokenService accessTokenService;

    @Resource
    private RateLimitHandler rateLimitHandler;
    
    @Resource
    private IReconciliationTaskService reconciliationTaskService;

    @GetMapping("/seckill/token/{id}")
    public Result<String> issueSeckillAccessToken(@PathVariable("id") Long voucherId) {
        Long userId = UserHolder.getUser().getId();
        rateLimitHandler.execute(voucherId, userId, RateLimitScene.ISSUE_TOKEN);
        String token = accessTokenService.issueAccessToken(voucherId, userId);
        return Result.ok(token);
    }

    @PostMapping("/seckill/{id}")
    public Result<Long> seckillVoucher(@PathVariable("id") Long voucherId,
                                       @RequestParam(name = "accessToken", required = false) String accessToken) {
        Long userId = UserHolder.getUser().getId();
        rateLimitHandler.execute(voucherId, userId, RateLimitScene.SECKILL_ORDER);
        if (accessTokenService.isEnabled()) {
            if (accessToken == null || !accessTokenService.validateAndConsume(voucherId, userId, accessToken)) {
                return Result.fail("令牌校验失败或令牌已失效");
            }
        }
        return voucherOrderService.seckillVoucher(voucherId);
    }
    
    @PostMapping("/get/seckill/voucher/order-id")
    public Result<Long> getSeckillVoucherOrder(@Valid @RequestBody GetVoucherOrderDto getVoucherOrderDto) {
        return Result.ok(voucherOrderService.getSeckillVoucherOrder(getVoucherOrderDto));
    }
    
    @PostMapping("/get/seckill/voucher/order-id/by/voucher-id")
    public Result<Long> getSeckillVoucherOrderIdByVoucherId(@Valid @RequestBody GetVoucherOrderByVoucherIdDto getVoucherOrderByVoucherIdDto) {
        return Result.ok(voucherOrderService.getSeckillVoucherOrderIdByVoucherId(getVoucherOrderByVoucherIdDto));
    }
    
    @PostMapping("/cancel")
    public Result<Boolean> cancel(@Valid @RequestBody CancelVoucherOrderDto cancelVoucherOrderDto) {
        return Result.ok(voucherOrderService.cancel(cancelVoucherOrderDto));
    }
    
    @PostMapping(value = "/reconciliation/task/all")
    public Result<Void> reconciliationTaskAll() {
        reconciliationTaskService.reconciliationTaskExecute();
        return Result.ok();
    }
}
