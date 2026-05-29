package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.entity.SeckillVoucher;
import org.xu.model.SeckillVoucherFullModel;

/**
 
 * @description: 秒杀优惠券 接口

 **/
public interface ISeckillVoucherService extends IService<SeckillVoucher> {
    
    SeckillVoucherFullModel queryByVoucherId(Long voucherId);
    
    void loadVoucherStock(Long voucherId);
    
    boolean rollbackStock(Long voucherId);
}
