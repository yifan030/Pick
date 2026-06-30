package org.xu.kafka.message;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * @description: 用户行为反馈消息
 **/

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UserBehaviorFeedbackMessage {

    private String eventId;
    private String userId;
    private String eventType;   // shop_card_click | purchase_success | explicit_rejection
    private String traceId;      // 关联推荐 trace_id
    private String shopId;
    private Long timestamp;
    private String sessionId;

    // 额外上下文（可选）
    private String context;      // JSON string，预留扩展
}
