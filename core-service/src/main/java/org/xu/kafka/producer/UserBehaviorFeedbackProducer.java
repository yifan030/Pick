package org.xu.kafka.producer;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import org.xu.AbstractProducerHandler;
import org.xu.kafka.message.UserBehaviorFeedbackMessage;
import org.xu.message.MessageExtend;

/**
 * Kafka 生产者：发送用户行为反馈事件。
 *
 * <p>反馈事件来源于 AI 推荐交互路径（商品卡片点击、购买转化、显式拒绝等），
 * 用于闭环训练和策略优化。属于非关键路径，发送失败不阻塞主流程。</p>
 */
@Slf4j
@Component
public class UserBehaviorFeedbackProducer extends AbstractProducerHandler<MessageExtend<UserBehaviorFeedbackMessage>> {

    @Value("${spring.kafka.topics.user-behavior-feedback}")
    private String topic;

    public UserBehaviorFeedbackProducer(KafkaTemplate<String, MessageExtend<UserBehaviorFeedbackMessage>> kafkaTemplate) {
        super(kafkaTemplate);
    }

    /**
     * 发送用户行为反馈事件到 Kafka。
     *
     * @param message 反馈事件消息体
     */
    public void sendFeedback(UserBehaviorFeedbackMessage message) {
        sendPayload(topic, message);
    }

    @Override
    protected void afterSendFailure(String topic, MessageExtend<UserBehaviorFeedbackMessage> message, Throwable throwable) {
        log.error("Failed to send feedback event: userId={}, eventType={}, error={}",
                message.getMessageBody().getUserId(), message.getMessageBody().getEventType(), throwable.getMessage());
        // 反馈事件是非关键路径，发送失败不阻塞主流程，只记录日志
    }
}
