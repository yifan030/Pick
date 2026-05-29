package org.xu.ratelimit.extension;

import org.xu.enums.BaseCode;

/**
 
 * @description: 默认空实现

 **/
public class NoOpRateLimitPenaltyPolicy implements RateLimitPenaltyPolicy {
    @Override
    public void apply(RateLimitContext ctx, BaseCode reason) {
        // no-op
    }
}