package com.sharedparking;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 业务后端启动类。
 *
 * 职责边界：只处理 HTTP 请求与业务逻辑，不加载任何视觉模型。
 * 车位状态由 backend/vision 的 Python 进程写入数据库，本服务只读。
 */
@SpringBootApplication
public class ParkingApplication {

    public static void main(String[] args) {
        SpringApplication.run(ParkingApplication.class, args);
    }
}
