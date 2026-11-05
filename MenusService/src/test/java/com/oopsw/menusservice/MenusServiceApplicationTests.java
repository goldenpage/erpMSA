package com.oopsw.menusservice;
import static org.assertj.core.api.Assertions.assertThat;
import com.auth0.jwt.JWT;
import com.oopsw.security.JwtTestKeys;
import com.oopsw.menusservice.menu.MenuRepository;
import java.net.URI;
import java.net.http.*;
import java.time.Instant;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.*;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,
 properties={"eureka.client.enabled=false","spring.cloud.discovery.enabled=false"})
@Import(TestDatabase.class)
@org.junit.jupiter.api.Tag("integration")
class MenusServiceApplicationTests {
    @LocalServerPort int port;
    @Autowired MenuRepository repository;
    @Autowired ObjectMapper mapper;
    @Autowired org.springframework.jdbc.core.JdbcTemplate jdbc;
    @DynamicPropertySource static void keys(DynamicPropertyRegistry registry) {registry.add("app.auth.public-key-directory",JwtTestKeys.PRIMARY::publicDirectory);}
    @BeforeEach void clear() {repository.deleteAllInBatch();}
    String token(long account,boolean expired) {
        return JWT.create().withKeyId(JwtTestKeys.PRIMARY.kid()).withIssuer("kosta-erp-account").withAudience("kosta-erp-api")
            .withSubject(""+account).withClaim("token_type","access").withClaim("email","test@example.com").withClaim("role","ROLE_USER")
            .withIssuedAt(Instant.now().minusSeconds(120)).withExpiresAt(Instant.now().plusSeconds(expired?-60:600)).sign(JwtTestKeys.PRIMARY.algorithm());
    }
    HttpResponse<String> request(String method,String path,String body,String token) throws Exception {
        var request=HttpRequest.newBuilder(URI.create("http://localhost:"+port+path)).header("Content-Type","application/json");
        if(token!=null)request.header("Authorization","Bearer "+token);
        return HttpClient.newHttpClient().send(request.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body)).build(),HttpResponse.BodyHandlers.ofString());
    }
    HttpResponse<String> create(String name) throws Exception {return request("POST","/menus","{\"name\":\""+name+"\",\"price\":12000}",token(1,false));}
    @Test void authenticationAndHealth() throws Exception {
        assertThat(request("GET","/menus",null,null).statusCode()).isEqualTo(401);
        assertThat(request("GET","/menus",null,token(1,true)).statusCode()).isEqualTo(401);
        assertThat(request("GET","/actuator/health",null,null).statusCode()).isEqualTo(200);
    }
    @Test void menuLifecycleAndOptimisticConflict() throws Exception {
        var created=create("볶음밥");assertThat(created.statusCode()).isEqualTo(201);
        long id=mapper.readTree(created.body()).get("menuId").asLong();
        assertThat(created.headers().firstValue("Location")).hasValue("/menus/"+id);
        var edited=request("PUT","/menus/"+id,"{\"name\":\"김치볶음밥\",\"price\":13000,\"status\":\"ACTIVE\",\"version\":0}",token(1,false));
        assertThat(edited.statusCode()).isEqualTo(200);assertThat(mapper.readTree(edited.body()).get("version").asLong()).isEqualTo(1);
        assertThat(request("PUT","/menus/"+id,"{\"name\":\"stale\",\"price\":1000,\"status\":\"ACTIVE\",\"version\":0}",token(1,false)).body()).contains("MENU_CONFLICT");
        assertThat(request("DELETE","/menus/"+id,null,token(1,false)).statusCode()).isEqualTo(204);
        assertThat(request("GET","/menus/"+id,null,token(1,false)).body()).contains("INACTIVE","김치볶음밥");
        assertThat(mapper.readTree(request("GET","/menus?status=ACTIVE",null,token(1,false)).body()).get("totalElements").asLong()).isZero();
        assertThat(repository.count()).isEqualTo(1);
    }
    @Test void tenantBoundaryIncludesWrites() throws Exception {
        long id=mapper.readTree(create("국밥").body()).get("menuId").asLong();
        assertThat(request("GET","/menus/"+id,null,token(2,false)).statusCode()).isEqualTo(404);
        assertThat(request("DELETE","/menus/"+id,null,token(2,false)).statusCode()).isEqualTo(404);
        assertThat(request("PUT","/menus/"+id,"{\"name\":\"other\",\"price\":1000,\"status\":\"ACTIVE\",\"version\":0}",token(2,false)).statusCode()).isEqualTo(404);
        assertThat(mapper.readTree(request("GET","/menus",null,token(2,false)).body()).get("totalElements").asLong()).isZero();
    }
    @Test void invalidInputsAndUnknownPaths() throws Exception {
        assertThat(request("POST","/menus","{\"name\":\"\",\"price\":-1}",token(1,false)).statusCode()).isEqualTo(400);
        for(String path:new String[]{"/menus?page=-1","/menus?size=101","/menus/0","/menus?status=UNKNOWN"})
            assertThat(request("GET",path,null,token(1,false)).statusCode()).isEqualTo(400);
        assertThat(request("GET","/menus/no/such/route",null,token(1,false)).statusCode()).isEqualTo(404);
    }
    @Test void paginationIsStableForEqualTimestamps() throws Exception {
        long first=mapper.readTree(create("A").body()).get("menuId").asLong();
        long second=mapper.readTree(create("B").body()).get("menuId").asLong();
        jdbc.update("UPDATE menu SET created_at='2026-01-01 00:00:00'");
        var page=request("GET","/menus?size=1&page=0",null,token(1,false));
        assertThat(mapper.readTree(page.body()).get("menus").get(0).get("menuId").asLong()).isEqualTo(second);
        assertThat(mapper.readTree(request("GET","/menus?size=1&page=1",null,token(1,false)).body()).get("menus").get(0).get("menuId").asLong()).isEqualTo(first);
    }

    @org.springframework.beans.factory.annotation.Autowired
    org.springframework.context.ApplicationContext drainContext;

    /** 종료 시 Eureka DOWN 알림 후 drain(shared/service-foundation)이 이 서비스에 연결됐는지 확인한다. */
    @Test void 종료_시_웹_서버보다_먼저_Eureka_DOWN_후_drain하도록_연결된다() {
        var drain = drainContext.getBean(com.oopsw.foundation.DiscoveryDrainLifecycle.class);
        var graceful = drainContext.getBeansOfType(org.springframework.context.SmartLifecycle.class).values().stream()
            .filter(bean -> bean.getClass().getSimpleName().equals("WebServerGracefulShutdownLifecycle"))
            .findFirst().orElseThrow();
        // 높은 phase가 먼저 멈춘다. drain이 끝난 뒤에 웹 서버 graceful shutdown이 시작된다.
        assertThat(drain.getPhase()).isGreaterThan(graceful.getPhase());
        assertThat(drain.drain()).isEqualTo(java.time.Duration.ofSeconds(15));
        // 테스트는 Eureka 클라이언트를 끈다. 알릴 대상이 없으면 기다리지 않고 바로 끝난다.
        assertThat(drainContext.getBeanProvider(com.netflix.appinfo.ApplicationInfoManager.class).getIfAvailable()).isNull();
        long started = System.nanoTime();
        drain.stop();
        assertThat(java.time.Duration.ofNanos(System.nanoTime() - started)).isLessThan(java.time.Duration.ofSeconds(1));
        drain.start();
    }
}
