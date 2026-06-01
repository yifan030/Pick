package org.xu.dto;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class ShopSyncDTO {
    private Long shopId;
    private String name;
    private String type;
    private String subType;
    private String area;
    private String address;
    private Double longitude;
    private Double latitude;
    private Long avgPrice;
    private Integer score;
    private String openHours;
    private String images;
    private String description;
    private String tags;
    private String recommendedScenes;
    private LocalDateTime updateTime;
}
