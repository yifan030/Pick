package org.xu.core;

import org.xu.servicelock.LockType;
import org.xu.servicelock.ServiceLocker;
import org.xu.servicelock.impl.RedissonFairLocker;
import org.xu.servicelock.impl.RedissonReadLocker;
import org.xu.servicelock.impl.RedissonReentrantLocker;
import org.xu.servicelock.impl.RedissonWriteLocker;
import org.redisson.api.RedissonClient;

import java.util.HashMap;
import java.util.Map;

import static org.xu.servicelock.LockType.Fair;
import static org.xu.servicelock.LockType.Read;
import static org.xu.servicelock.LockType.Reentrant;
import static org.xu.servicelock.LockType.Write;

/**
  
 * @description: 缓存

 **/
public class ManageLocker {

    private final Map<LockType, ServiceLocker> cacheLocker = new HashMap<>();
    
    public ManageLocker(RedissonClient redissonClient){
        cacheLocker.put(Reentrant,new RedissonReentrantLocker(redissonClient));
        cacheLocker.put(Fair,new RedissonFairLocker(redissonClient));
        cacheLocker.put(Write,new RedissonWriteLocker(redissonClient));
        cacheLocker.put(Read,new RedissonReadLocker(redissonClient));
    }
    
    public ServiceLocker getReentrantLocker(){
        return cacheLocker.get(Reentrant);
    }
    
    public ServiceLocker getFairLocker(){
        return cacheLocker.get(Fair);
    }
    
    public ServiceLocker getWriteLocker(){
        return cacheLocker.get(Write);
    }
    
    public ServiceLocker getReadLocker(){
        return cacheLocker.get(Read);
    }
}
