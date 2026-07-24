package com.oopsw.gatewayserver;


import static org.springframework.cloud.gateway.server.mvc.filter.BeforeFilterFunctions.uri;
import static org.springframework.cloud.gateway.server.mvc.handler.GatewayRouterFunctions.route;
import static org.springframework.cloud.gateway.server.mvc.handler.HandlerFunctions.http;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerResponse;

@Configuration
public class GatewayRouteConfig {
    //@Bean
    //public RouterFunction<ServerResponse> accountRoutes() {
    //    return route("user-service").GET("/account/**", http()).before(uri(
    //        "http://localhost:7001")).build();
    //}
}
