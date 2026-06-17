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
@TableName("tb_reservation")
public class Reservation implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id")
    private Long id;

    private Long userId;

    private Long shopId;

    /** 0=排队取号, 1=电话预约 */
    private Integer type;

    private Integer guests;

    private LocalDateTime reserveTime;

    private String contactPhone;

    /** 0=待确认, 1=已确认, 2=已取消, 3=已完成 */
    private Integer status;

    private String remark;

    private Integer queueNumber;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
