package org.xu.servicelock.factory;

import org.xu.core.ManageLocker;
import org.xu.servicelock.LockType;
import org.xu.servicelock.ServiceLocker;
import lombok.AllArgsConstructor;

/**
  
 * @description: 工厂

 **/
@AllArgsConstructor
public class ServiceLockFactory {
    
    private final ManageLocker manageLocker;
    

    public ServiceLocker getLock(LockType lockType){
        ServiceLocker lock;
        switch (lockType) {
            case Fair:
                lock = manageLocker.getFairLocker();
                break;
            case Write:
                lock = manageLocker.getWriteLocker();
                break;
            case Read:
                lock = manageLocker.getReadLocker();
                break;
            default:
                lock = manageLocker.getReentrantLocker();
                break;
        }
        return lock;
    }
}
