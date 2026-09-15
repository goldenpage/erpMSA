package com.oopsw.foundation;

import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;

@Configuration(proxyBeanMethods = false)
@Import({JwtAccessFilter.class, PendingDomainController.class})
public class ServiceFoundationConfiguration {}
