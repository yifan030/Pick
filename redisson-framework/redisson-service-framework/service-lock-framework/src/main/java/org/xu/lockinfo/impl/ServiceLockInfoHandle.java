package org.xu.lockinfo.impl;

import org.xu.lockinfo.AbstractLockInfoHandle;

/**
  
 * @description: 锁信息

 **/
public class ServiceLockInfoHandle extends AbstractLockInfoHandle {

    private static final String LOCK_PREFIX_NAME = "SERVICE_LOCK";
    
    @Override
    protected String getLockPrefixName() {
        return LOCK_PREFIX_NAME;
    }
}
