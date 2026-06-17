package org.xu.config;

import jakarta.annotation.Resource;
import org.xu.sync.InternalTokenInterceptor;
import org.xu.utils.LoginInterceptor;
import org.xu.utils.RefreshTokenInterceptor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 
 * @description: 跨域配置

 **/
@Configuration
public class MvcConfig implements WebMvcConfigurer {

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Value("${sync.internal-token}")
    private String internalToken;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 内部 API 认证拦截器
        registry.addInterceptor(new InternalTokenInterceptor(internalToken))
                .addPathPatterns("/api/sync/**", "/api/voucher-order/internal/**", "/api/orders/internal/**")
                .order(0);
        // 登录拦截器
        registry.addInterceptor(new LoginInterceptor())
                .excludePathPatterns(
                        "/shop/**",
                        "/voucher/**",
                        "/shop-type/**",
                        "/upload/**",
                        "/blog/hot",
                        "/user/code",
                        "/user/login"
                ).order(1);
        // token刷新的拦截器
        registry.addInterceptor(new RefreshTokenInterceptor(stringRedisTemplate)).addPathPatterns("/**").order(0);
    }
}
