-- Match the account/status predicate and stable descending listing order.
-- Keep the narrower account/status index: count queries can still use it.
CREATE INDEX idx_item_account_status_created
    ON item (account_id, status, created_at, id);
