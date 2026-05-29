package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.dto.DelayVoucherReminderDto;
import org.xu.dto.Result;
import org.xu.dto.SeckillVoucherDto;
import org.xu.dto.UpdateSeckillVoucherDto;
import org.xu.dto.UpdateSeckillVoucherStockDto;
import org.xu.dto.VoucherDto;
import org.xu.dto.VoucherSubscribeBatchDto;
import org.xu.dto.VoucherSubscribeDto;
import org.xu.entity.Voucher;
import org.xu.vo.GetSubscribeStatusVo;

import java.util.List;

/**
 
 * @description: 优惠券 接口

 **/
public interface IVoucherService extends IService<Voucher> {

    Long addVoucher(VoucherDto voucherDto);
    
    Result<List<Voucher>> queryVoucherOfShop(Long shopId);

    Long addSeckillVoucher(SeckillVoucherDto seckillVoucherDto);
    
    void updateSeckillVoucher(UpdateSeckillVoucherDto updateSeckillVoucherDto);
    
    void updateSeckillVoucherStock(UpdateSeckillVoucherStockDto updateSeckillVoucherDto);
    
    void subscribe(VoucherSubscribeDto voucherSubscribeDto);
    
    void unsubscribe(VoucherSubscribeDto voucherSubscribeDto);
    
    Integer getSubscribeStatus(VoucherSubscribeDto voucherSubscribeDto);
    
    List<GetSubscribeStatusVo> getSubscribeStatusBatch(VoucherSubscribeBatchDto voucherSubscribeBatchDto);
    
    void delayVoucherReminder(DelayVoucherReminderDto delayVoucherReminderDto);
}
