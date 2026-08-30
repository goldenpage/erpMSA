package com.oopsw.auditservice.config;

import java.util.Map;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.common.TopicPartition;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.FixedBackOff;

@Configuration
public class KafkaConfig {

    @Bean
    NewTopic accountLifecycleTopic(
        @Value("${app.kafka.topics.account-lifecycle}") String topicName
    ) {
        return TopicBuilder.name(topicName)
            .partitions(3)
            .replicas(1)
            .build();
    }

    @Bean
    NewTopic accountLifecycleDltTopic(
        @Value("${app.kafka.topics.account-lifecycle-dlt}") String topicName
    ) {
        return TopicBuilder.name(topicName)
            .partitions(3)
            .replicas(1)
            .configs(Map.of("retention.ms", "604800000"))
            .build();
    }

    @Bean
    DefaultErrorHandler kafkaErrorHandler(
        KafkaTemplate<String, String> kafkaTemplate,
        @Value("${app.kafka.topics.account-lifecycle-dlt}") String dltTopic
    ) {
        DeadLetterPublishingRecoverer recoverer =
            new DeadLetterPublishingRecoverer(
                kafkaTemplate,
                (record, exception) -> new TopicPartition(
                    dltTopic,
                    record.partition()
                )
            );
        DefaultErrorHandler errorHandler = new DefaultErrorHandler(
            recoverer,
            new FixedBackOff(1000L, 2L)
        );
        errorHandler.addNotRetryableExceptions(IllegalArgumentException.class);
        return errorHandler;
    }
}
