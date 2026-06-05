package org.xu.controller;


import jakarta.annotation.Resource;
import jakarta.validation.Valid;
import org.xu.dto.DelayVoucherReminderDto;
import org.xu.dto.GetSeckillVoucherDto;
import org.xu.dto.Result;
import org.xu.dto.SeckillVoucherDto;
import org.xu.dto.UpdateSeckillVoucherDto;
import org.xu.dto.UpdateSeckillVoucherStockDto;
import org.xu.dto.VoucherAvailableRequestDTO;
import org.xu.dto.VoucherDto;
import org.xu.dto.VoucherSubscribeBatchDto;
import org.xu.dto.VoucherSubscribeDto;
import org.xu.entity.Voucher;
import org.xu.model.SeckillVoucherFullModel;
import org.xu.service.ISeckillVoucherService;
import org.xu.service.IVoucherService;
import org.xu.vo.GetSubscribeStatusVo;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;


/**
 
 * @description: 优惠券api

 **/
@RestController
@RequestMapping("/voucher")
public class VoucherController {

    @Resource
    private IVoucherService voucherService;

    @Resource
    private ISeckillVoucherService seckillVoucherService;

    @Value("${sync.internal-token}")
    private String internalToken;
    
    @PostMapping("/get")
    public Result<SeckillVoucherFullModel> get(@Valid @RequestBody GetSeckillVoucherDto getSeckillVoucherDto) {
        return Result.ok(seckillVoucherService.queryByVoucherId(getSeckillVoucherDto.getVoucherId()));
    }
    
    @PostMapping("/seckill")
    public Result<Long> addSeckillVoucher(@Valid @RequestBody SeckillVoucherDto seckillVoucherDto) {
        final Long voucherId = voucherService.addSeckillVoucher(seckillVoucherDto);
        return Result.ok(voucherId);
    }

    @PostMapping("/update/seckill")
    public Result<Void> updateSeckillVoucher(@Valid @RequestBody UpdateSeckillVoucherDto updateSeckillVoucherDto) {
        voucherService.updateSeckillVoucher(updateSeckillVoucherDto);
        return Result.ok();
    }
    
    @PostMapping("/update/seckill/stock")
    public Result<Void> updateSeckillVoucherStock(@Valid @RequestBody UpdateSeckillVoucherStockDto updateSeckillVoucherDto) {
        voucherService.updateSeckillVoucherStock(updateSeckillVoucherDto);
        return Result.ok();
    }

    @PostMapping
    public Result<Long> addVoucher(@Valid @RequestBody VoucherDto voucherDto) {
        final Long voucherId = voucherService.addVoucher(voucherDto);
        return Result.ok(voucherId);
    }
    
    @GetMapping("/list/{shopId}")
    public Result<List<Voucher>> queryVoucherOfShop(@PathVariable("shopId") Long shopId) {
       return voucherService.queryVoucherOfShop(shopId);
    }
    
    @PostMapping("/subscribe")
    public Result<Void> subscribe(@Valid @RequestBody VoucherSubscribeDto voucherSubscribeDto){
        voucherService.subscribe(voucherSubscribeDto);
        return Result.ok();
    }
    
    @PostMapping("/unsubscribe")
    public Result<Void> unsubscribe(@Valid @RequestBody VoucherSubscribeDto voucherSubscribeDto){
        voucherService.unsubscribe(voucherSubscribeDto);
        return Result.ok();
    }
    
    @PostMapping("/get/subscribe/status")
    public Result<Integer> getSubscribeStatus(@Valid @RequestBody VoucherSubscribeDto voucherSubscribeDto){
        return Result.ok(voucherService.getSubscribeStatus(voucherSubscribeDto));
    }
    
    @PostMapping("/get/subscribe/status/batch")
    public Result<List<GetSubscribeStatusVo>> getSubscribeStatusBatch(@Valid @RequestBody VoucherSubscribeBatchDto voucherSubscribeBatchDto){
        return Result.ok(voucherService.getSubscribeStatusBatch(voucherSubscribeBatchDto));
    }
    
    @PostMapping("/delay/voucher/reminder")
    public Result<Void> delayVoucherReminder(@Valid @RequestBody DelayVoucherReminderDto delayVoucherReminderDto){
        voucherService.delayVoucherReminder(delayVoucherReminderDto);
        return Result.ok();
    }

    @PostMapping("/available-by-shop-ids")
    public Result<Map<String, List<Voucher>>> queryAvailableByShopIds(
            @RequestBody VoucherAvailableRequestDTO request,
            @RequestHeader(value = "X-Internal-Token", required = false) String internalTokenHeader) {
        // 内部调用校验 token；前端走 sa-token
        if (internalTokenHeader != null && !internalToken.equals(internalTokenHeader)) {
            return Result.fail("Unauthorized");
        }
        return voucherService.queryAvailableByShopIds(
                request.getShopIds(), request.getUserId());
    }

    @GetMapping("/{id}")
    public Result<Voucher> getVoucherById(@PathVariable("id") Long voucherId) {
        Voucher voucher = voucherService.getById(voucherId);
        if (voucher == null) {
            return Result.fail("券不存在");
        }
        return Result.ok(voucher);
    }
}
