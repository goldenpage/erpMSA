import json
import unittest

import account_lab as al
import lab


class SeedRuleTest(unittest.TestCase):
    def test_status_counts_match_rule(self):
        for accounts in [100, 101, 199, 1_000_000, 1_234_567]:
            counts = {'ACTIVE': 0, 'PENDING': 0, 'SUSPENDED': 0}
            if accounts <= 2_000:
                for seq in range(1, accounts + 1):
                    counts[al.status_of(seq)] += 1
                self.assertEqual(counts, al.expected_status_counts(accounts))
            self.assertEqual(sum(al.expected_status_counts(accounts).values()), accounts)

    def test_chunks_cover_range_without_overlap(self):
        ranges = al.chunks(1_000_000)
        self.assertEqual(ranges[0], (1, 100_000))
        self.assertEqual(ranges[-1], (900_001, 1_000_000))
        self.assertEqual(sum(end - start + 1 for start, end in ranges), 1_000_000)
        self.assertEqual(al.chunks(150_001)[-1], (100_001, 150_001))

    def test_seed_sql_rejects_non_bcrypt_value(self):
        with self.assertRaises(ValueError):
            al.seed_sql(1, 10, "x'; DROP TABLE account; --")
        sql = al.seed_sql(1, 10, '$2a$10$' + 'a' * 53)
        self.assertIn('mydb.seq_1_to_10', sql)
        self.assertIn("CONCAT('9',LPAD(seq,9,'0'))", sql)

    def test_business_id_ranges_do_not_overlap(self):
        # seed 9xxxxxxxxx, fixture 8000000000, register 7RR…, duplicate 6RR…
        self.assertEqual(len('9' + '1'.zfill(9)), 10)
        self.assertEqual(len(al.FIXTURE_BID), 10)
        self.assertNotEqual(al.FIXTURE_BID[0], '9')


class ReconcileTest(unittest.TestCase):
    def test_clean_run_passes(self):
        outbox = [('e1', 1, 'PUBLISHED'), ('e2', 2, 'PUBLISHED')]
        kafka = [{'eventId': 'e1', 'accountId': 1}, {'eventId': 'e2', 'accountId': 2}, {'eventId': 'x', 'accountId': 99}]
        summary = al.reconcile([1, 2], outbox, kafka)
        self.assertEqual(summary['kafkaRecords'], 2)
        self.assertEqual(al.verdict(summary, 2, 0)['result'], 'PASS')

    def test_duplicate_publication_is_reported_not_failed(self):
        outbox = [('e1', 1, 'PUBLISHED')]
        kafka = [{'eventId': 'e1', 'accountId': 1}, {'eventId': 'e1', 'accountId': 1}]
        summary = al.reconcile([1], outbox, kafka)
        result = al.verdict(summary, 1, 0)
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['duplicatePublications'], 1)

    def test_missing_event_and_count_mismatch_fail(self):
        summary = al.reconcile([1, 2], [('e1', 1, 'PUBLISHED')], [])
        result = al.verdict(summary, 3, 0)
        self.assertEqual(result['result'], 'FAIL')
        joined = ' '.join(result['failures'])
        self.assertIn('accountsWithoutEvent=1', joined)
        self.assertIn('publishedMissingInKafka=1', joined)
        self.assertIn('k6 201 count 3', joined)

    def test_undrained_outbox_fails(self):
        summary = al.reconcile([1], [('e1', 1, 'PENDING')], [])
        self.assertEqual(al.verdict(summary, 1, 1)['result'], 'FAIL')


class RedeployProbeTest(unittest.TestCase):
    def test_summary_counts_failures_and_recovery_lag(self):
        samples = [(0.0, 405), (1.0, 500), (2.0, 0), (3.0, 503), (4.0, 405), (6.0, 500), (7.0, 405)]
        summary = al.summarize_probe(samples, healthy_at=3.5)
        self.assertEqual(summary['failures'], 4)
        self.assertEqual(summary['statusCounts']['500'], 2)
        self.assertEqual(summary['failuresAfterHealthy'], 1)
        self.assertEqual(summary['recoveryLagSeconds'], 2.5)
        self.assertEqual(summary['firstSuccessAfterHealthy'], 4.0)
        self.assertEqual(al.summarize_probe([(0.0, 405)])['failures'], 0)

    def test_disposal_reconcile_passes_only_when_ledger_matches(self):
        records = [{'disposalId': 'a', 'status': 'COMPLETED', 'quantity': 1},
                   {'disposalId': 'b', 'status': 'PENDING', 'quantity': 1},
                   {'disposalId': 'c', 'status': 'COMPLETED', 'quantity': 1}]
        ledger = [{'requestId': 'DISPOSAL-a', 'quantityDelta': -1}, {'requestId': 'DISPOSAL-c', 'quantityDelta': -1}]
        result = al.reconcile_disposals(records, ledger, 10, 8)
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['finalStatusCounts'], {'COMPLETED': 2, 'PENDING': 1})
        # 같은 폐기를 두 번 차감
        self.assertEqual(al.reconcile_disposals(records, ledger + [ledger[0]], 10, 7)['result'], 'FAIL')
        # PENDING을 성공으로 처리해 차감한 경우
        self.assertEqual(al.reconcile_disposals(records, ledger + [{'requestId': 'DISPOSAL-b', 'quantityDelta': -1}], 10, 7)['result'], 'FAIL')
        # 현재고 불일치
        self.assertEqual(al.reconcile_disposals(records, ledger, 10, 9)['result'], 'FAIL')

    def test_targets_use_approved_service_paths(self):
        services = json.loads((lab.ROOT / 'architecture/services.json').read_text())['services']
        approved = {s['path'][1:] + '-service': s['path'] for s in services}
        for service, path, _ in al.REDEPLOY_TARGETS.values():
            self.assertIn(service, approved)
            self.assertTrue(path.startswith(approved[service]), path)


class ParsingTest(unittest.TestCase):
    def test_k6_counter_reads_summary_shapes(self):
        self.assertEqual(al.k6_counter({'metrics': {'c': {'values': {'count': 7}}}}, 'c'), 7)
        self.assertEqual(al.k6_counter({'metrics': {}}, 'c'), 0)

    def test_redis_info(self):
        info = al.parse_info('# Memory\r\nused_memory:1024\r\nmaxmemory:0\r\n# Keyspace\r\ndb0:keys=12,expires=12,avg_ttl=1\r\n')
        self.assertEqual(info['keys'], 12)
        self.assertEqual(info['used_memory'], '1024')

    def test_stage_validation(self):
        self.assertEqual(al.validate_stages('50:2m,100:30s'), '50:2m,100:30s')
        for bad in ['50', '50:2m;rm', '30000:1m']:
            with self.assertRaises(ValueError):
                al.validate_stages(bad)


if __name__ == '__main__':
    unittest.main()
