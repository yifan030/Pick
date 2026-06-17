package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.dto.CancelVoucherOrderDto;
import org.xu.dto.GetVoucherOrderByVoucherIdDto;
import org.xu.dto.GetVoucherOrderDto;
import org.xu.dto.Result;
import org.xu.entity.VoucherOrder;
import org.xu.kafka.message.SeckillVoucherMessage;
import org.xu.message.MessageExtend;

import java.util.List;
import java.util.Map;

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

    /**
     * 查询订单状态（供 Python Agent 内部调用）
     */
    Map<String, Object> getOrderStatus(Long orderId);

    /**
     * 查询用户订单列表（供 Python Agent 内部调用）
     * @param status 可选：NORMAL / CANCEL / REFUND / USED
     */
    List<Map<String, Object>> listUserOrders(Long userId, String status);

    /**
     * 申请退款（供 Python Agent 内部调用）
     * @return 退款后新的订单 ID（退款操作生成的记录）
     */
    Long requestRefund(Long orderId, String reason);
}
