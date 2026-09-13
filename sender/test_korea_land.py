import unittest
from unittest.mock import patch
from sender import korea_land, sender


DOMESTIC = {
    '서울': (37.5665, 126.9780), '청주': (36.6424, 127.4890),
    '부산': (35.1796, 129.0756), '제주': (33.4996, 126.5312),
    '울릉도': (37.5, 130.87), '독도 동도': (37.241, 131.869),
    '독도 서도': (37.242, 131.865), '백령도': (37.96, 124.67),
    '대청도': (37.825, 124.713), '연평도': (37.665, 125.697),
    '흑산도': (34.68, 125.42), '홍도': (34.687, 125.197),
    '마라도': (33.117, 126.267), '가거도': (34.052, 125.125),
    '강화도': (37.746, 126.488), '거제도': (34.881, 128.621),
}
FOREIGN_OR_SEA = {
    '평양': (39.0392, 125.7625), '개성': (37.9708, 126.5544),
    '해주': (38.04, 125.71), '원산': (39.15, 127.44),
    '대마도': (34.2, 129.29), '후쿠오카': (33.59, 130.4),
    '히로시마': (34.385, 132.455), '칭다오': (36.067, 120.383),
    '중국 웨이하이': (37.51, 122.12), '동해': (37.0, 130.0),
    '서해': (35.5, 124.7), '대한해협': (34.8, 129.5),
}


class KoreaLandTests(unittest.TestCase):
    def test_domestic_mainland_and_islands(self):
        for name, point in DOMESTIC.items():
            with self.subTest(name=name):
                self.assertTrue(korea_land.contains(*point))

    def test_foreign_and_sea(self):
        for name, point in FOREIGN_OR_SEA.items():
            with self.subTest(name=name):
                self.assertFalse(korea_land.contains(*point))

    def test_non_finite(self):
        self.assertFalse(korea_land.contains(float('nan'), 127))
        self.assertFalse(korea_land.contains(37, float('inf')))

    def test_ring_edges_and_holes(self):
        outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
        hole = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
        with patch.object(korea_land, '_polygons', return_value=[((0, 0, 4, 4), [outer, hole])]):
            self.assertTrue(korea_land.contains(0, 2))
            self.assertTrue(korea_land.contains(0.5, 0.5))
            self.assertFalse(korea_land.contains(2, 2))
            self.assertFalse(korea_land.contains(5, 5))

    @patch.object(sender, '_put_heartbeat')
    @patch.object(sender, 'read_heartbeat', return_value={})
    @patch.object(sender, 'notify_admin')
    def test_foreign_only_sends_nothing(self, notify, read, put):
        sender.check_sk_master_alert(list(FOREIGN_OR_SEA.values()))
        notify.assert_not_called()
        put.assert_not_called()

    @patch.object(sender, '_put_heartbeat')
    @patch.object(sender, 'read_heartbeat', return_value={'sk_active': True})
    @patch.object(sender, 'notify_admin')
    def test_mixed_counts_only_domestic_and_ignores_old_state(self, notify, read, put):
        sender.check_sk_master_alert([DOMESTIC['독도 동도'], FOREIGN_OR_SEA['대마도']])
        notify.assert_called_once()
        self.assertIn('1건', notify.call_args.args[0])
        self.assertTrue(put.call_args.args[0]['sk_land_v1_active'])

    @patch.object(sender, '_put_heartbeat')
    @patch.object(sender, 'read_heartbeat', return_value={'sk_land_v1_active': True})
    @patch.object(sender, 'notify_admin')
    def test_continuing_domestic_does_not_repeat(self, notify, read, put):
        sender.check_sk_master_alert([DOMESTIC['서울']])
        notify.assert_not_called()

    @patch.object(sender, '_put_heartbeat')
    @patch.object(sender, 'read_heartbeat', return_value={'sk_land_v1_active': True})
    @patch.object(sender, 'notify_admin')
    def test_foreign_only_rearms_domestic(self, notify, read, put):
        sender.check_sk_master_alert([FOREIGN_OR_SEA['대마도']])
        notify.assert_not_called()
        self.assertFalse(put.call_args.args[0]['sk_land_v1_active'])

    @patch.object(sender, 'is_south_korea', side_effect=OSError('missing boundary'))
    @patch.object(sender, 'notify_admin')
    def test_boundary_failure_does_not_send_or_raise(self, notify, contains):
        sender.check_sk_master_alert([DOMESTIC['서울']])
        notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
