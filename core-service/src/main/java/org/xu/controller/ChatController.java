package org.xu.controller;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClient;
import org.xu.dto.ChatRequestDTO;

import java.io.IOException;
import java.io.OutputStream;

/**
 * SSE 透明代理：前端 SSE 请求 → 转发 Python /chat → 原始字节流透传到前端。
 * 不做解析、不做过滤、不修改任何字节。
 */
@RestController
public class ChatController {

    @Value("${agent-service.url:http://localhost:8000}")
    private String agentServiceUrl;

    @Value("${sync.internal-token}")
    private String internalToken;

    @PostMapping("/api/chat/stream")
    public void chatStream(@RequestBody ChatRequestDTO request, HttpServletResponse response) {
        response.setContentType("text/event-stream");
        response.setCharacterEncoding("UTF-8");

        OutputStream os;
        try {
            os = response.getOutputStream();
        } catch (IOException e) {
            return;
        }

        WebClient client = WebClient.builder()
                .baseUrl(agentServiceUrl)
                .defaultHeader("X-Internal-Token", internalToken)
                .build();

        // 原始字节流透传：读取 DataBuffer → 写入 OutputStream → 释放
        client.post()
                .uri("/chat")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(request)
                .retrieve()
                .bodyToFlux(DataBuffer.class)
                .doOnNext(buffer -> {
                    try {
                        byte[] bytes = new byte[buffer.readableByteCount()];
                        buffer.read(bytes);
                        os.write(bytes);
                        os.flush();
                    } catch (IOException ignored) {
                    } finally {
                        DataBufferUtils.release(buffer);
                    }
                })
                .doOnError(e -> {
                    try {
                        os.write("data: {\"type\":\"error\",\"content\":\"抱歉，服务暂时不可用，请稍后再试\"}\n\n"
                                .getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        os.write("data: {\"type\":\"done\"}\n\n"
                                .getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        os.flush();
                    } catch (IOException ignored) {
                    }
                })
                .blockLast();

        try {
            os.close();
        } catch (IOException ignored) {
        }
    }
}
