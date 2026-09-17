ALTER TABLE stock_movement
    DROP CONSTRAINT chk_movement_type,
    ADD CONSTRAINT chk_movement_type CHECK (movement_type IN ('INITIAL','ADJUSTMENT','DISPOSAL'));
