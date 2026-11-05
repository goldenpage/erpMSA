import unittest

import account_report as ar


class StageMathTest(unittest.TestCase):
    def test_expected_rate_follows_linear_ramp(self):
        points = ar.profile('10:1m,10:1m', 0)
        # 0→10 선형 증가 구간의 평균은 5, 유지 구간은 10
        self.assertAlmostEqual(ar.expected_rate(points, 0, 60), 5, places=1)
        self.assertAlmostEqual(ar.expected_rate(points, 60, 120), 10, places=1)

    def test_stage_windows_skip_settle_and_average_target(self):
        windows = ar.stage_windows('5:1m,10:1m', settle=15, start_rate=1)
        self.assertEqual([(w['start'], w['end']) for w in windows], [(15, 60), (75, 120)])
        self.assertAlmostEqual(windows[1]['target'], 5 + 5 * (75 - 60 + (120 - 60 - 15) / 2) / 60, places=1)

    def test_percentile_and_tags(self):
        self.assertEqual(ar.percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(ar.percentile(list(range(1, 101)), 95), 95)
        self.assertIsNone(ar.percentile([], 95))
        self.assertEqual(ar.tags({'name': 'GET /x', 'extra_tags': 'kind=normal'}), 'GET /x|normal')
        self.assertEqual(ar.tags({'name': 'GET /x', 'extra_tags': ''}), 'GET /x|-')


if __name__ == '__main__':
    unittest.main()
