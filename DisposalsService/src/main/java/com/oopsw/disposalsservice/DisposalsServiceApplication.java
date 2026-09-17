package com.oopsw.disposalsservice;

import com.oopsw.foundation.JwtAccessFilter;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;

@SpringBootApplication
@Import(JwtAccessFilter.class)
public class DisposalsServiceApplication {
    public static void main(String[] args) { SpringApplication.run(DisposalsServiceApplication.class, args); }
}
