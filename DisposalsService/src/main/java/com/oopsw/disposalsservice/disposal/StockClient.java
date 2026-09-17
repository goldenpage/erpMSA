package com.oopsw.disposalsservice.disposal;
public interface StockClient {
    Result dispose(DisposalController.View disposal,String authorization);
    record Result(boolean applied,Long movementId,Long quantityAfter,String rejectionCode) {
        public static Result pending() {return new Result(false,null,null,null);}
        public static Result rejected(String code) {return new Result(false,null,null,code);}
        public static Result applied(long id,long quantity) {return new Result(true,id,quantity,null);}
    }
}
