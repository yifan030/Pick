package org.xu.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("tb_shop_image")
public class ShopImage implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id")
    private Long id;

    private Long shopId;

    private String url;

    private String type;

    private String alt;

    private Integer sort;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
