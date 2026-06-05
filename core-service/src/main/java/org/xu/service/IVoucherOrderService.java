package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.dto.CancelVoucherOrderDto;
import org.xu.dto.GetVoucherOrderByVoucherIdDto;
import org.xu.dto.GetVoucherOrderDto;
import org.xu.dto.Result;
import org.xu.entity.VoucherOrder;
import org.xu.kafka.message.SeckillVoucherMessage;
import org.xu.message.MessageExtend;

/**
 
 * @description: 优惠券订单 接口

 **/
public interface IVoucherOrderService extends IService<VoucherOrder> {

    Result<Long> seckillVoucher(Long voucherId);

    void createVoucherOrderV1(VoucherOrder voucherOrder);
    
    boolean createVoucherOrderV2(MessageExtend<SeckillVoucherMessage> message);
    
    Long getSeckillVoucherOrder(GetVoucherOrderDto getVoucherOrderDto);
    
    Boolean cancel(CancelVoucherOrderDto cancelVoucherOrderDto);
    
    boolean autoIssueVoucherToEarliestSubscriber(final Long voucherId, final Long excludeUserId);
    
    Long getSeckillVoucherOrderIdByVoucherId(GetVoucherOrderByVoucherIdDto getVoucherOrderByVoucherIdDto);

    /**
     * 内部下单（供 Python Agent 调用，不走 seckill 流程）
     */
    Long createOrderInternal(Long voucherId, Long userId, int quantity);
}
