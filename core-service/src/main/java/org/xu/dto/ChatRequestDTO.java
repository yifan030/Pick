package org.xu.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class ChatRequestDTO {
    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("user_id")
    private Long userId;

    private String query;
    private Double longitude;
    private Double latitude;
}
