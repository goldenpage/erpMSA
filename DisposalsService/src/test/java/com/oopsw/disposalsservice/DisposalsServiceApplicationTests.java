package com.oopsw.disposalsservice;
import static org.assertj.core.api.Assertions.assertThat;
import com.auth0.jwt.JWT;
import com.oopsw.security.JwtTestKeys;
import com.oopsw.disposalsservice.disposal.DisposalRepository;
import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.*;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,
 properties={"eureka.client.enabled=false","spring.cloud.discovery.enabled=false","app.inventory.discovery-enabled=false"})
@Import(TestDatabase.class)
class DisposalsServiceApplicationTests {
    static final ObjectMapper JSON=new ObjectMapper();
    static final AtomicLong quantity=new AtomicLong(20);
    static final AtomicInteger calls=new AtomicInteger();
    static final AtomicBoolean loseResponse=new AtomicBoolean();
    static final Map<String,String> applied=new ConcurrentHashMap<>();
    static final HttpServer STOCK=startStock();
    static HttpServer startStock() {
        try {
            var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
            server.createContext("/foodmaterials/inventories/",exchange->{
                calls.incrementAndGet();
                String authorization=exchange.getRequestHeaders().getFirst("Authorization");
                var input=JSON.readTree(exchange.getRequestBody());
                String command=input.get("requestId").asString();long amount=input.get("quantity").asLong();
                String path=exchange.getRequestURI().getPath();int status=200;String body;
                synchronized(applied) {
                    if(!JWT.decode(authorization.substring(7)).getSubject().equals("1") || !path.equals("/foodmaterials/inventories/100/disposals")) {
                        status=404;body="{\"code\":\"INVENTORY_NOT_FOUND\"}";
                    } else if(applied.containsKey(command)) body=applied.get(command);
                    else if(amount>quantity.get()) {status=409;body="{\"code\":\"INSUFFICIENT_STOCK\"}";}
                    else {
                        long remaining=quantity.addAndGet(-amount);
                        body=JSON.writeValueAsString(Map.of("movementId",applied.size()+1,"foodMaterialId",100,"requestId",command,"movementType","DISPOSAL","quantityDelta",-amount,"quantityAfter",remaining));
                        applied.put(command,body);
                    }
                    // A stock commit followed by an unusable response must not cause double deduction on retry.
                    if(loseResponse.getAndSet(false)) {status=503;body="{\"code\":\"RESPONSE_LOST\"}";}
                }
                byte[] bytes=body.getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");
                exchange.sendResponseHeaders(status,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
            });server.start();return server;
        } catch(Exception exception) {throw new IllegalStateException(exception);}
    }
    @LocalServerPort int port;
    @Autowired DisposalRepository repository;
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory",JwtTestKeys.PRIMARY::publicDirectory);
        registry.add("app.inventory.base-url",()->"http://127.0.0.1:"+STOCK.getAddress().getPort());
    }
    @BeforeEach void clear() {repository.deleteAllInBatch();quantity.set(20);calls.set(0);applied.clear();loseResponse.set(false);}
    @AfterAll static void stop() {STOCK.stop(0);}
    String token(long account) {
        return JWT.create().withKeyId(JwtTestKeys.PRIMARY.kid()).withIssuer("kosta-erp-account").withAudience("kosta-erp-api")
            .withSubject(""+account).withClaim("token_type","access").withClaim("email","test@example.com").withClaim("role","ROLE_USER")
            .withIssuedAt(Instant.now()).withExpiresAt(Instant.now().plusSeconds(600)).sign(JwtTestKeys.PRIMARY.algorithm());
    }
    HttpResponse<String> request(String method,String path,String body,long account) throws Exception {
        var request=HttpRequest.newBuilder(URI.create("http://localhost:"+port+path)).header("Content-Type","application/json");
        if(account>0)request.header("Authorization","Bearer "+token(account));
        return HttpClient.newHttpClient().send(request.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body)).build(),HttpResponse.BodyHandlers.ofString());
    }
    String body(String id,long count) {return "{\"requestId\":\""+id+"\",\"foodMaterialId\":100,\"quantity\":"+count+",\"reason\":\"유통기한 경과\"}";}
    @Test void completedAndDuplicateRequestsHaveOneStockEffect() throws Exception {
        var first=request("POST","/disposals",body("ONE",3),1);assertThat(first.statusCode()).isEqualTo(200);
        var record=JSON.readTree(first.body());assertThat(record.get("status").asString()).isEqualTo("COMPLETED");
        assertThat(record.get("quantityAfter").asLong()).isEqualTo(17);
        var again=request("POST","/disposals",body("ONE",3),1);
        assertThat(JSON.readTree(again.body()).get("disposalId").asString()).isEqualTo(record.get("disposalId").asString());
        assertThat(calls.get()).isEqualTo(1);assertThat(quantity.get()).isEqualTo(17);assertThat(repository.count()).isEqualTo(1);
    }
    @Test void lostResponseRecoversWithSameCommandId() throws Exception {
        loseResponse.set(true);
        var first=request("POST","/disposals",body("LOST",3),1);assertThat(first.statusCode()).isEqualTo(202);
        var record=JSON.readTree(first.body());assertThat(record.get("status").asString()).isEqualTo("PENDING");
        assertThat(quantity.get()).isEqualTo(17);
        var retry=request("POST","/disposals/"+record.get("disposalId").asString()+"/retry",null,1);
        assertThat(retry.statusCode()).isEqualTo(200);assertThat(retry.body()).contains("COMPLETED");
        assertThat(quantity.get()).isEqualTo(17);assertThat(applied).hasSize(1);assertThat(calls.get()).isEqualTo(2);
    }
    @Test void rejectedRequestsRemainRecordedWithoutStockChange() throws Exception {
        var result=request("POST","/disposals",body("TOO-MUCH",21),1);
        assertThat(result.statusCode()).isEqualTo(409);assertThat(result.body()).contains("REJECTED","INSUFFICIENT_STOCK");
        assertThat(request("POST","/disposals",body("TOO-MUCH",21),1).statusCode()).isEqualTo(409);
        assertThat(quantity.get()).isEqualTo(20);assertThat(calls.get()).isEqualTo(1);
    }
    @Test void conflictingPayloadAndTenantBoundaries() throws Exception {
        String id=JSON.readTree(request("POST","/disposals",body("ID",2),1).body()).get("disposalId").asString();
        assertThat(request("POST","/disposals",body("ID",3),1).body()).contains("REQUEST_CONFLICT");
        assertThat(request("GET","/disposals/"+id,null,2).statusCode()).isEqualTo(404);
        assertThat(request("POST","/disposals/"+id+"/retry",null,2).statusCode()).isEqualTo(404);
        assertThat(JSON.readTree(request("GET","/disposals",null,2).body()).get("totalElements").asLong()).isZero();
        assertThat(request("POST","/disposals",body("OTHER",1),2).body()).contains("REJECTED","INVENTORY_NOT_FOUND");
        assertThat(quantity.get()).isEqualTo(18);
    }
    @Test void concurrentRetriesSerializeOneLogicalDisposal() throws Exception {
        var barrier=new CyclicBarrier(8);
        try(var executor=Executors.newFixedThreadPool(8)) {
            var futures=new ArrayList<Future<HttpResponse<String>>>();
            for(int i=0;i<8;i++) futures.add(executor.submit(()->{barrier.await(10,TimeUnit.SECONDS);return request("POST","/disposals",body("SAME",3),1);}));
            var ids=new HashSet<String>();
            for(var f:futures) {var result=f.get(30,TimeUnit.SECONDS);assertThat(result.statusCode()).isEqualTo(200);ids.add(JSON.readTree(result.body()).get("disposalId").asString());}
            assertThat(ids).hasSize(1);
        }
        assertThat(repository.count()).isEqualTo(1);assertThat(calls.get()).isEqualTo(1);assertThat(quantity.get()).isEqualTo(17);
    }
    @Test void validationAndAuthentication() throws Exception {
        assertThat(request("GET","/disposals",null,0).statusCode()).isEqualTo(401);
        assertThat(request("GET","/actuator/health",null,0).statusCode()).isEqualTo(200);
        assertThat(request("POST","/disposals",body("INVALID",0),1).statusCode()).isEqualTo(400);
        assertThat(request("GET","/disposals?page=-1",null,1).statusCode()).isEqualTo(400);
        assertThat(request("GET","/disposals?status=UNKNOWN",null,1).statusCode()).isEqualTo(400);
        assertThat(calls.get()).isZero();
    }
}
