package org.xu.dto;

import lombok.Data;

@Data
public class ShopImageDTO {
    private Long id;
    private Long shopId;
    private String url;
    private String type;
    private String alt;
    private Integer sort;
}
