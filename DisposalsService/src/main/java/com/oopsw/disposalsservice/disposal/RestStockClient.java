package com.oopsw.disposalsservice.disposal;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpHeaders;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

public class RestStockClient implements StockClient {
    private final RestClient client;
    private final ObjectMapper mapper;
    public RestStockClient(RestClient client,ObjectMapper mapper) {this.client=client;this.mapper=mapper;}
    @Override
    public Result dispose(DisposalController.View disposal,String authorization) {
        String command="DISPOSAL-"+disposal.disposalId();
        try {
            return client.post().uri("/foodmaterials/inventories/{id}/disposals",disposal.foodMaterialId())
                .header(HttpHeaders.AUTHORIZATION,authorization)
                .body(Map.of("requestId",command,"quantity",disposal.quantity(),"reason",disposal.reason()))
                .exchange((request,response)-> {
                    var body=mapper.readTree(response.getBody());
                    if(response.getStatusCode().value()==200) {
                        if(!body.path("requestId").asString().equals(command)
                            || !body.path("movementType").asString().equals("DISPOSAL")
                            || body.path("foodMaterialId").asLong()!=disposal.foodMaterialId()
                            || body.path("quantityDelta").asLong()!=-disposal.quantity()
                            || !body.path("movementId").isIntegralNumber() || body.path("movementId").asLong()<=0
                            || !body.path("quantityAfter").isIntegralNumber() || body.path("quantityAfter").asLong()<0) return Result.pending();
                        return Result.applied(body.get("movementId").asLong(),body.get("quantityAfter").asLong());
                    }
                    String code=body.path("code").asString("");
                    if((response.getStatusCode().value()==404 || response.getStatusCode().value()==409)
                        && Set.of("INVENTORY_NOT_FOUND","INSUFFICIENT_STOCK","DISPOSAL_REQUEST_CONFLICT").contains(code)) return Result.rejected(code);
                    return Result.pending();
                });
        } catch(Exception exception) {
            // A timeout can occur after stock commit. Preserve the command ID and retry, never assume rollback.
            return Result.pending();
        }
    }
}
