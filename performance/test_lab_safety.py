import json
import subprocess
import unittest
from unittest.mock import patch
import lab

class VolumeSafetyTest(unittest.TestCase):
    def verify(self, volumes):
        result = subprocess.CompletedProcess([], 0, json.dumps({'volumes': volumes}))
        with patch.object(lab, 'compose', return_value=result):
            lab.verify_volume_names()

    def test_rejects_inherited_application_volume(self):
        with self.assertRaises(SystemExit):
            self.verify({'grafana-data': {'name': 'erpmsa-grafana-data'}})

    def test_rejects_external_volume_even_with_lab_prefix(self):
        with self.assertRaises(SystemExit):
            self.verify({'data': {'name': lab.PROJECT + '-data', 'external': True}})

    def test_accepts_only_project_scoped_volumes(self):
        self.verify({'data': {'name': lab.PROJECT + '-data'}})

if __name__ == '__main__': unittest.main()
