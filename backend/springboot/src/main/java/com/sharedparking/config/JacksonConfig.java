package com.sharedparking.config;

import com.fasterxml.jackson.datatype.jsr310.deser.LocalDateDeserializer;
import com.fasterxml.jackson.datatype.jsr310.deser.LocalDateTimeDeserializer;
import com.fasterxml.jackson.datatype.jsr310.ser.LocalDateSerializer;
import com.fasterxml.jackson.datatype.jsr310.ser.LocalDateTimeSerializer;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.format.DateTimeFormatter;

/**
 * 时间序列化配置。
 *
 * 【为什么需要这个类】application.yml 里的 spring.jackson.date-format 只对
 * java.util.Date 生效，对 LocalDateTime 完全无效 —— 实测会输出成
 * "2026-11-19T15:49:55"（中间带个 T）。
 * 前端拿到这种格式要么显示难看，要么得自己 replace('T', ' ')，所以在这里统一处理。
 *
 * 反序列化也一起配：前端提交 "2026-11-20 09:00:00" 时能直接转成 LocalDateTime，
 * 不用在每个 DTO 上写 @JsonFormat。
 */
@Configuration
public class JacksonConfig {

    private static final DateTimeFormatter DATE_TIME =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final DateTimeFormatter DATE =
            DateTimeFormatter.ofPattern("yyyy-MM-dd");

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer jacksonCustomizer() {
        return builder -> {
            builder.serializers(new LocalDateTimeSerializer(DATE_TIME));
            builder.deserializers(new LocalDateTimeDeserializer(DATE_TIME));
            builder.serializers(new LocalDateSerializer(DATE));
            builder.deserializers(new LocalDateDeserializer(DATE));
        };
    }
}
