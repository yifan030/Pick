-- sql/3_add_reservation_table.sql
-- Reservation — sharded by user_id MOD 2

CREATE TABLE IF NOT EXISTS `tb_reservation` (
    `id` BIGINT NOT NULL COMMENT '主键',
    `user_id` BIGINT NOT NULL COMMENT '用户ID',
    `shop_id` BIGINT NOT NULL COMMENT '店铺ID',
    `type` TINYINT NOT NULL DEFAULT 0 COMMENT '类型: 0=排队取号, 1=电话预约',
    `guests` INT NOT NULL DEFAULT 1 COMMENT '人数',
    `reserve_time` DATETIME COMMENT '预约时间（电话预约时必填）',
    `contact_phone` VARCHAR(20) COMMENT '联系电话',
    `status` TINYINT NOT NULL DEFAULT 0 COMMENT '状态: 0=待确认, 1=已确认, 2=已取消, 3=已完成',
    `remark` VARCHAR(500) COMMENT '备注',
    `queue_number` INT COMMENT '排队号',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_shop_id` (`shop_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='到店预约/排队表';
