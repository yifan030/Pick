package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.dto.GetVoucherOrderRouterDto;
import org.xu.entity.VoucherOrderRouter;

/**
 
 * @description: 优惠券订单路由 接口

 **/
public interface IVoucherOrderRouterService extends IService<VoucherOrderRouter> {
    
    Long get(GetVoucherOrderRouterDto getVoucherOrderRouterDto);
}
