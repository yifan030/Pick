package org.xu.config;

import org.xu.constant.LockInfoType;
import org.xu.handle.RedissonDataHandle;
import org.xu.locallock.LocalLockCache;
import org.xu.lockinfo.LockInfoHandle;
import org.xu.lockinfo.factory.LockInfoHandleFactory;
import org.xu.lockinfo.impl.RepeatExecuteLimitLockInfoHandle;
import org.xu.repeatexecutelimit.aspect.RepeatExecuteLimitAspect;
import org.xu.servicelock.factory.ServiceLockFactory;
import org.springframework.context.annotation.Bean;

/**
  
 * @description: 配置

 **/
public class RepeatExecuteLimitAutoConfiguration {
    
    @Bean(LockInfoType.REPEAT_EXECUTE_LIMIT)
    public LockInfoHandle repeatExecuteLimitHandle(){
        return new RepeatExecuteLimitLockInfoHandle();
    }
    
    @Bean
    public RepeatExecuteLimitAspect repeatExecuteLimitAspect(LocalLockCache localLockCache,
                                                             LockInfoHandleFactory lockInfoHandleFactory,
                                                             ServiceLockFactory serviceLockFactory,
                                                             RedissonDataHandle redissonDataHandle){
        return new RepeatExecuteLimitAspect(localLockCache, lockInfoHandleFactory,serviceLockFactory,redissonDataHandle);
    }
}
    