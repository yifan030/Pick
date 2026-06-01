package org.xu.dto;

import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.Data;

import java.time.LocalDateTime;

@Data
public class BlogSyncDTO {
    private Long blogId;
    private Long shopId;
    @JsonIgnore
    private Long userId;
    private String userNickname;
    private String title;
    private String content;
    private LocalDateTime updateTime;
}
