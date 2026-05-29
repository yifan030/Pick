package org.xu.servicelock.annotion;

import org.xu.servicelock.LockType;
import org.xu.servicelock.info.LockTimeOutStrategy;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.util.concurrent.TimeUnit;

/**
  
 * @description: 注解

 **/
@Target(value= {ElementType.TYPE, ElementType.METHOD})
@Retention(value= RetentionPolicy.RUNTIME)
public @interface ServiceLock {
    
    LockType lockType() default LockType.Reentrant;
    
    String name() default "";
   
    String [] keys();
    
    long waitTime() default 10;
    
    TimeUnit timeUnit() default TimeUnit.SECONDS;
    
    LockTimeOutStrategy lockTimeoutStrategy() default LockTimeOutStrategy.FAIL;
    
    String customLockTimeoutStrategy() default "";
}
