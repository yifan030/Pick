package org.xu.service;

import com.baomidou.mybatisplus.extension.service.IService;
import org.xu.dto.VoucherReconcileLogDto;
import org.xu.entity.VoucherReconcileLog;
import org.xu.kafka.message.SeckillVoucherMessage;
import org.xu.message.MessageExtend;

/**
 
 * @description: 对账日志 接口

 **/
public interface IVoucherReconcileLogService extends IService<VoucherReconcileLog> {
    
    boolean saveReconcileLog(Integer logType,
                             Integer businessType,
                             String detail,
                             MessageExtend<SeckillVoucherMessage> message);
    
    boolean saveReconcileLog(Integer logType,
                             Integer businessType,
                             String detail,
                             Long traceId,
                             MessageExtend<SeckillVoucherMessage> message);
    
    
    boolean saveReconcileLog(VoucherReconcileLogDto voucherReconcileLogDto);
}