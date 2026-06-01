package org.xu.sync;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.servlet.HandlerInterceptor;

public class InternalTokenInterceptor implements HandlerInterceptor {

    private final String expectedToken;

    public InternalTokenInterceptor(String expectedToken) {
        this.expectedToken = expectedToken;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String token = request.getHeader("X-Internal-Token");
        if (!expectedToken.equals(token)) {
            response.setStatus(401);
            return false;
        }
        return true;
    }
}
