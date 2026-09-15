package com.oopsw.noticesservice;

import com.oopsw.foundation.ServiceFoundationConfiguration;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;

@SpringBootApplication
@Import(ServiceFoundationConfiguration.class)
public class NoticesServiceApplication {
    public static void main(String[] args) { SpringApplication.run(NoticesServiceApplication.class, args); }
}
