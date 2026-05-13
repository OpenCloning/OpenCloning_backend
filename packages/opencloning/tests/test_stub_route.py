from fastapi.testclient import TestClient
import unittest
import shutil
import os
import tempfile
from opencloning_linkml.datamodel import ManuallyTypedSource, RestrictionEnzymeDigestionSource, ManuallyTypedSequence
from pytest import MonkeyPatch
from importlib import reload
from pydna.dseqrecord import Dseqrecord

from opencloning.dna_functions import format_sequence_genbank
import opencloning.get_router as get_router
import opencloning.endpoints.no_input as no_input_endpoints
import opencloning.endpoints.no_assembly as no_assembly_endpoints
import opencloning.main as main
import opencloning.app_settings as app_settings


class StubRouteTest(unittest.TestCase):
    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._workdir = tempfile.mkdtemp()
        os.chdir(self._workdir)

        MonkeyPatch().setenv('RECORD_STUBS', '1')
        reload(app_settings)
        reload(get_router)
        reload(no_input_endpoints)
        reload(no_assembly_endpoints)
        reload(main)

        self.client = TestClient(main.app)

    def tearDown(self):
        MonkeyPatch().setenv('RECORD_STUBS', '0')
        reload(app_settings)
        reload(get_router)
        reload(no_input_endpoints)
        reload(no_assembly_endpoints)
        reload(main)

        os.chdir(self._prev_cwd)
        shutil.rmtree(self._workdir, ignore_errors=True)

    def test_stub_route(self):
        source = ManuallyTypedSource(id=0)
        sequence = ManuallyTypedSequence(id=0, sequence='ATGC')
        data = {'source': source.model_dump(), 'sequence': sequence.model_dump()}

        response = self.client.post('/manually_typed', json=data)
        self.assertEqual(response.status_code, 200)

        self.assertTrue(os.path.exists('stubs/manually_typed/'))
        self.assertTrue(len(os.listdir('stubs/manually_typed/')), 1)

        # Also works for 422 response
        source_dict = source.model_dump()
        source_dict['user_input'] = 'io'
        response = self.client.post('/manually_typed', json=source_dict)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(os.listdir('stubs/manually_typed/')), 2)

        # Works for 404
        dseq = Dseqrecord('AAAAAAGAATTCTTTTTT', circular=False)
        json_seq = format_sequence_genbank(dseq)
        json_seq.id = 1

        # One enzyme
        source = RestrictionEnzymeDigestionSource(id=0)
        data = {'source': source.model_dump(), 'sequences': [json_seq.model_dump()]}
        response = self.client.post('/restriction', json=data, params={'restriction_enzymes': ['helloworld']})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(os.listdir('stubs/restriction/')), 1)


if __name__ == '__main__':
    unittest.main()
