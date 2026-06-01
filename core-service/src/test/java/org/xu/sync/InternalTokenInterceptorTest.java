package org.xu.sync;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InternalTokenInterceptorTest {

    private static final String EXPECTED_TOKEN = "test-internal-token";

    @Test
    void shouldReturn401WhenTokenMissing() throws Exception {
        var interceptor = new InternalTokenInterceptor(EXPECTED_TOKEN);
        var request = mock(HttpServletRequest.class);
        var response = mock(HttpServletResponse.class);

        boolean result = interceptor.preHandle(request, response, null);

        assertFalse(result);
        verify(response).setStatus(401);
    }

    @Test
    void shouldReturn401WhenTokenMismatch() throws Exception {
        var interceptor = new InternalTokenInterceptor(EXPECTED_TOKEN);
        var request = mock(HttpServletRequest.class);
        var response = mock(HttpServletResponse.class);
        when(request.getHeader("X-Internal-Token")).thenReturn("wrong-token");

        boolean result = interceptor.preHandle(request, response, null);

        assertFalse(result);
        verify(response).setStatus(401);
    }

    @Test
    void shouldPassWhenTokenMatches() throws Exception {
        var interceptor = new InternalTokenInterceptor(EXPECTED_TOKEN);
        var request = mock(HttpServletRequest.class);
        var response = mock(HttpServletResponse.class);
        when(request.getHeader("X-Internal-Token")).thenReturn(EXPECTED_TOKEN);

        boolean result = interceptor.preHandle(request, response, null);

        assertTrue(result);
    }
}
