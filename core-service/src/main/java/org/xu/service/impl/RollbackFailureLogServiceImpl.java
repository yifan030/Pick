package org.xu.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import org.xu.entity.RollbackFailureLog;
import org.xu.mapper.RollbackFailureLogMapper;
import org.xu.service.IRollbackFailureLogService;
import org.springframework.stereotype.Service;

/**
 
 * @description: 回滚失败日志 接口实现

 **/
@Service
public class RollbackFailureLogServiceImpl extends ServiceImpl<RollbackFailureLogMapper, RollbackFailureLog>
        implements IRollbackFailureLogService {
}