package org.xu.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serial;
import java.io.Serializable;

/**
 * 新增商铺请求 DTO
 *
 * @description: 新增商铺
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
public class SaveShopDTO implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    /**
     * 商铺名称
     */
    @NotBlank
    private String name;

    /**
     * 商铺类型 ID
     */
    @NotNull
    private Long typeId;

    /**
     * 商铺图片，多个图片以','隔开；未传默认空字符串
     */
    private String images;

    /**
     * 商圈，例如陆家嘴
     */
    private String area;

    /**
     * 地址
     */
    @NotBlank
    private String address;

    /**
     * 经度
     */
    @NotNull
    private Double longitude;

    /**
     * 纬度
     */
    @NotNull
    private Double latitude;

    /**
     * 均价，取整数
     */
    private Long avgPrice;

    /**
     * 评分，1~5分，乘10保存，避免小数
     */
    @NotNull
    private Integer score;

    /**
     * 营业时间，例如 10:00-22:00
     */
    private String openHours;

    /**
     * 店铺详细描述（RAG 核心检索素材）
     */
    private String description;

    /**
     * 标签列表，如 ["停车方便","有包厢","适合约会"]
     */
    private String tags;

    /**
     * 推荐场景列表，如 ["约会","家庭聚餐","商务宴请"]
     */
    private String recommendedScenes;
}
