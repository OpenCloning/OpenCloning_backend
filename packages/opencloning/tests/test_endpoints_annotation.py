from fastapi.testclient import TestClient
from pydna.dseqrecord import Dseqrecord
import unittest
import json
import pytest
from importlib import reload
import respx
import httpx
from fastapi import HTTPException
import os
import re

from opencloning.dna_functions import format_sequence_genbank, read_dsrecord_from_json, annotate_with_plannotate
import opencloning.app_settings as app_settings
import opencloning.http_client as http_client
import opencloning.endpoints.annotation as annotation_endpoints
import opencloning.main as _main
from opencloning_linkml.datamodel import (
    TextFileSequence,
    AnnotationSource,
)

test_files = os.path.join(os.path.dirname(__file__), 'test_files')

client = TestClient(_main.app)

dummy_url = 'http://dummy/url'


class PlannotateTest(unittest.TestCase):
    def setUp(self):
        # Has to be imported here to get the right environment variable
        pytest.MonkeyPatch().setenv('PLANNOTATE_URL', dummy_url)

        reload(app_settings)
        reload(http_client)
        reload(annotation_endpoints)
        reload(_main)
        self.client = TestClient(_main.app)

    def tearDown(self):
        pytest.MonkeyPatch().setenv('PLANNOTATE_URL', '')
        reload(app_settings)
        reload(http_client)
        reload(annotation_endpoints)
        reload(_main)

    @respx.mock
    def test_plannotate(self):
        seq = Dseqrecord(
            'AAAAttgagatcctttttttctgcgcgtaatctgctgcttgcaaacaaaaaaaccaccgctaccagcggtggtttgtttgccggatcaagagctaccaactctttttccgaaggtaactggcttcagcagagcgcagataccaaatactgttcttctagtgtagccgtagttaggccaccacttcaagaactctgtagcaccgcctacatacctcgctctgctaatcctgttaccagtggctgctgccagtggcgataagtcgtgtcttaccgggttggactcaagacgatagttaccggataaggcgcagcggtcgggctgaacggggggttcgtgcacacagcccagcttggagcgaacgacctacaccgaactgagatacctacagcgtgagctatgagaaagcgccacgcttcccgaagggagaaaggcggacaggtatccggtaagcggcagggtcggaacaggagagcgcacgagggagcttccagggggaaacgcctggtatctttatagtcctgtcgggtttcgccacctctgacttgagcgtcgatttttgtgatgctcgtcaggggggcggagcctatggaaaAAAA'
        )
        seq = format_sequence_genbank(seq)
        mock_response_success = json.load(open(f'{test_files}/planottate/mock_response_success.json'))
        # Mock the HTTPX GET request
        respx.post(f'{dummy_url}/annotate').respond(200, json=mock_response_success)

        source = AnnotationSource(id=0, annotation_tool='plannotate')
        response = self.client.post(
            '/annotate/plannotate', json={'sequence': seq.model_dump(), 'source': source.model_dump()}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        seq = read_dsrecord_from_json(TextFileSequence.model_validate(payload['sequences'][0]))
        source = payload['sources'][0]
        self.assertEqual(source['annotation_tool'], 'plannotate')
        self.assertEqual(source['annotation_tool_version'], '1.2.2')
        self.assertEqual(len(source['annotation_report']), 2)
        feature_names = [f.qualifiers['label'][0] for f in seq.features]
        self.assertIn('ori', feature_names)
        self.assertIn('RNAI', feature_names)

    @respx.mock
    def test_plannotate_down(self):
        respx.post(f'{dummy_url}/annotate').mock(side_effect=httpx.ConnectError('Connection error'))
        seq = Dseqrecord('aaa')
        seq = format_sequence_genbank(seq)
        source = AnnotationSource(id=0, annotation_tool='plannotate')
        response = self.client.post(
            '/annotate/plannotate', json={'sequence': seq.model_dump(), 'source': source.model_dump()}
        )
        self.assertEqual(response.status_code, 500)

    @respx.mock
    def test_plannotate_timeout(self):
        respx.post(f'{dummy_url}/annotate').mock(side_effect=httpx.TimeoutException('Timeout error'))
        seq = Dseqrecord('aaa')
        seq = format_sequence_genbank(seq)
        source = AnnotationSource(id=0, annotation_tool='plannotate')
        response = self.client.post(
            '/annotate/plannotate', json={'sequence': seq.model_dump(), 'source': source.model_dump()}
        )
        self.assertEqual(response.status_code, 504)


class PlannotateAsyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Has to be imported here to get the right environment variable
        pytest.MonkeyPatch().setenv('PLANNOTATE_URL', dummy_url)

        reload(app_settings)
        reload(http_client)
        reload(annotation_endpoints)
        reload(_main)
        self.client = TestClient(_main.app)

    def tearDown(self):
        pytest.MonkeyPatch().setenv('PLANNOTATE_URL', '')
        reload(app_settings)
        reload(http_client)
        reload(annotation_endpoints)
        reload(_main)

    @respx.mock
    async def test_plannotate_other_error(self):
        # This is tested here because it's impossible to send a malformed request from the backend
        respx.post(f'{dummy_url}/annotate').respond(400, json={'error': 'bad request'})

        with pytest.raises(HTTPException) as e:
            await annotate_with_plannotate('hello', 'hello.blah', f'{dummy_url}/annotate')
        self.assertEqual(e.value.status_code, 400)


class AnnotationTest(unittest.TestCase):

    attB1 = 'ACAACTTTGTACAAAAAAGCAGAAG'
    attB2 = 'ACAACTTTGTACAAGAAAGCTGGGC'
    greedy_attP1 = 'CAAATAATGATTTTATTTTGACTGATAGTGACCTGTTCGTTGCAACAAATTGATAAGCAATGCTTTTTTATAATGCCAACTTTGTACAAAAAAGCTGAACGAGAAACGTAAAATGATATAAATATCAATATATTAAATTAGATTTTGCATAAAAAACAGACTACATAATACTGTAAAACACAACATATCCAGTCA'

    def test_get_gateway_sites(self):
        seq = Dseqrecord('aaa' + self.attB1 + 'ccc' + self.attB2 + 'ccc' + self.greedy_attP1)
        response = client.post('/annotation/get_gateway_sites', json=format_sequence_genbank(seq).model_dump())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('attB1', payload)
        self.assertIn('attB2', payload)
        self.assertNotIn('attP1', payload)

        response = client.post(
            '/annotation/get_gateway_sites',
            json=format_sequence_genbank(seq).model_dump(),
            params={'greedy': True},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('attB1', payload)
        self.assertIn('attB2', payload)
        self.assertIn('attP1', payload)


def parse_primer_bind_features(genbank_text: str) -> set[tuple[str, int, int, int]]:
    """(label, start, end, strand) of the primer_bind features of a genbank file, with 0-based coordinates."""
    features = re.findall(r'^     primer_bind\s+(\S+)\n((?:^(?!\s{5}\S).*\n)*)', genbank_text, re.M)
    out = set()
    for location, body in features:
        body = ' '.join(line.strip() for line in body.split('\n'))
        label = re.search(r'/label="([^"]*)"', body).group(1).strip()
        match = re.match(r'(complement\()?(\d+)\.\.(\d+)', location)
        out.add((label, int(match.group(2)) - 1, int(match.group(3)), -1 if match.group(1) else 1))
    return out


class PrimerBindingSitesFixture:
    """Shared data and helpers for the primer binding site tests. Holds no tests itself."""

    data_dir = os.path.join(test_files, 'primer_binding_sites')

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(cls.data_dir, 'pGreen_0029_GFP_nonSTOP.gb')) as f:
            cls.template_genbank = f.read()
        with open(os.path.join(cls.data_dir, 'pGreen_0029_GFP_nonSTOP_reference_primers.gb')) as f:
            cls.reference_sites = parse_primer_bind_features(f.read())
        with open(os.path.join(cls.data_dir, 'primers.tsv')) as f:
            cls.all_primers = [
                {'id': i, 'name': line.split('\t')[0].strip(), 'sequence': line.split('\t')[1].strip()}
                for i, line in enumerate(f.read().splitlines()[1:], start=2)
                if line.strip()
            ]

    def template_sequence(self, id=1):
        return TextFileSequence(
            id=id,
            file_content=self.template_genbank,
            sequence_file_format='genbank',
            overhang_crick_3prime=0,
            overhang_watson_3prime=0,
        ).model_dump()

    def annotate(self, primers, sequence=None, settings=None, **params):
        source = AnnotationSource(id=100, annotation_tool='primer_binding_sites')
        body = {
            'sequence': self.template_sequence() if sequence is None else sequence,
            'source': source.model_dump(),
            'primers': primers,
        }
        if settings is not None:
            body['settings'] = settings
        return client.post('/annotate/primer_binding_sites', json=body, params=params)

    def named(self, name):
        return [p for p in self.all_primers if p['name'].strip() == name]

    def report_of(self, response):
        return {
            entry['primer_name']: entry
            for entry in response.json()['sources'][0]['annotation_report']
            if entry['start_location'] is not None
        }


class PrimerBindingSitesTest(PrimerBindingSitesFixture, unittest.TestCase):
    """Annotation of the binding sites of a set of primers.

    The reference file is not reproduced coordinate for coordinate, because the program that
    produced it records which 5' part of each primer is a designed tail and does not count it
    towards the footprint. Here it is only asserted that every site of the reference is found,
    possibly over a longer footprint.
    """

    def test_all_reference_sites_are_found(self):
        response = self.annotate(self.all_primers, minimal_annealing=14)
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        found = parse_primer_bind_features(payload['sequences'][0]['file_content'])
        # Every site of the reference is found, either with the same coordinates or with a
        # longer footprint (the reference does not extend into 5' tails that also match)
        for label, start, end, strand in self.reference_sites:
            overlapping = [
                site
                for site in found
                if site[0] == label and site[3] == strand and site[1] <= start and site[2] >= end
            ]
            self.assertEqual(len(overlapping), 1, f'reference site {label} {start}..{end} not found')

        source = payload['sources'][0]
        self.assertEqual(source['annotation_tool'], 'primer_binding_sites')
        self.assertIsNotNone(source['annotation_tool_version'])

    def test_report_includes_primers_that_do_not_bind(self):
        response = self.annotate(self.all_primers, minimal_annealing=14)
        report = response.json()['sources'][0]['annotation_report']

        bound = [r for r in report if r['start_location'] is not None]
        unbound = [r for r in report if r['start_location'] is None]
        self.assertEqual(len(bound), 29)
        self.assertEqual(len(unbound), 15)
        # 42 primers, of which 27 bind (2 of them in 2 places)
        self.assertEqual(len({r['primer_id'] for r in report}), len(self.all_primers))
        for entry in report:
            self.assertEqual(entry['type'], 'PrimerBindingAnnotationReport')
            self.assertIsNotNone(entry['primer_length'])

    def test_only_bound_primers_are_inputs(self):
        response = self.annotate(self.all_primers, minimal_annealing=14)
        source = response.json()['sources'][0]
        report = source['annotation_report']

        bound_ids = sorted({r['primer_id'] for r in report if r['start_location'] is not None})
        self.assertEqual([i['sequence'] for i in source['input']], [1] + bound_ids)

    def test_primer_binding_twice(self):
        # pAF binds in two places, because the region is duplicated in the plasmid
        response = self.annotate(self.named('pAF'), minimal_annealing=14)
        found = parse_primer_bind_features(response.json()['sequences'][0]['file_content'])
        self.assertEqual(len(found), 2)
        self.assertEqual({site[3] for site in found}, {1})

    def test_primer_with_5prime_tail_is_partially_annotated(self):
        # GFPsense_F is 30 bp, but its 5' XhoI site does not anneal
        (primer,) = self.named('GFPsense_F')
        response = self.annotate([primer], minimal_annealing=14)
        ((_, start, end, strand),) = parse_primer_bind_features(response.json()['sequences'][0]['file_content'])
        self.assertEqual((start, end, strand), (1442, 1466, 1))
        self.assertLess(end - start, len(primer['sequence']))

    def test_primer_that_does_not_bind(self):
        response = self.annotate(self.named('XVE_F'), minimal_annealing=14)
        payload = response.json()
        self.assertEqual(parse_primer_bind_features(payload['sequences'][0]['file_content']), set())
        (entry,) = payload['sources'][0]['annotation_report']
        self.assertIsNone(entry['start_location'])
        self.assertEqual(entry['primer_name'], 'XVE_F')
        self.assertEqual(payload['sources'][0]['input'], [{'type': 'SourceInput', 'sequence': 1}])

    def test_minimal_annealing_too_high_loses_short_primers(self):
        # M13R is only 16 bp long
        self.assertEqual(len(parse_primer_bind_features(self.annotate_named_output('M13R', 16))), 1)
        self.assertEqual(len(parse_primer_bind_features(self.annotate_named_output('M13R', 17))), 0)

    def annotate_named_output(self, name, minimal_annealing):
        response = self.annotate(self.named(name), minimal_annealing=minimal_annealing)
        return response.json()['sequences'][0]['file_content']

    def test_allowed_mismatches(self):
        # NPTIIR does not bind anywhere with 0 mismatches
        self.assertEqual(len(parse_primer_bind_features(self.annotate_named_output('NPTIIR', 14))), 0)

        # With a mismatch budget it binds, and the reported number of mismatches is the real
        # one in the annotated footprint, not the budget
        for allowed, expected_footprint in ((1, (3753, 3767)), (2, (3753, 3768))):
            response = self.annotate(self.named('NPTIIR'), minimal_annealing=14, allowed_mismatches=allowed)
            (entry,) = [
                r for r in response.json()['sources'][0]['annotation_report'] if r['start_location'] is not None
            ]
            self.assertEqual((entry['start_location'], entry['end_location']), expected_footprint)
            self.assertEqual(entry['mismatches'], allowed)
            self.assertEqual(entry['strand'], -1)

    def test_mismatches_do_not_shrink_the_footprint_below_minimal_annealing(self):
        # A candidate whose perfect run is shorter than the minimal annealing length must not
        # be annotated as a shorter feature
        for allowed in (0, 1, 2, 3):
            response = self.annotate(self.all_primers, minimal_annealing=18, allowed_mismatches=allowed)
            found = parse_primer_bind_features(response.json()['sequences'][0]['file_content'])
            for label, start, end, _ in found:
                self.assertGreaterEqual(end - start, 18, f'{label} annotated over only {end - start} bp')

    def test_mismatch_on_the_3prime_base_rejects_the_site(self):
        # A polymerase does not extend from an unpaired 3' end, so such a site does not prime
        # whatever the mismatch budget. gfp-genomF binds at 1530..1549 with a perfect match.
        (primer,) = self.named('gfp-genomF')
        mutated_3prime = primer['sequence'][:-1] + ('A' if primer['sequence'][-1] != 'A' else 'C')
        mutated_5prime = ('A' if primer['sequence'][0] != 'A' else 'C') + primer['sequence'][1:]

        for allowed in (0, 1, 2):
            response = self.annotate(
                [{**primer, 'sequence': mutated_3prime}], minimal_annealing=14, allowed_mismatches=allowed
            )
            found = parse_primer_bind_features(response.json()['sequences'][0]['file_content'])
            self.assertEqual(found, set(), f'3-prime mismatch annotated with budget {allowed}')

        # The same mismatch on the 5' end is only a shorter footprint, or is absorbed by the budget
        response = self.annotate([{**primer, 'sequence': mutated_5prime}], minimal_annealing=14)
        ((_, start, end, _),) = parse_primer_bind_features(response.json()['sequences'][0]['file_content'])
        self.assertEqual((start, end), (1530, 1549))
        response = self.annotate([{**primer, 'sequence': mutated_5prime}], minimal_annealing=14, allowed_mismatches=1)
        ((_, start, end, _),) = parse_primer_bind_features(response.json()['sequences'][0]['file_content'])
        self.assertEqual((start, end), (1529, 1549))

    def test_perfect_matches_are_unaffected_by_the_mismatch_budget(self):
        # M13R matches perfectly over its whole length, so the budget changes nothing
        for allowed in (0, 1, 2, 3):
            response = self.annotate(self.named('M13R'), minimal_annealing=14, allowed_mismatches=allowed)
            self.assertEqual(
                parse_primer_bind_features(response.json()['sequences'][0]['file_content']),
                {('M13R', 503, 519, 1)},
            )

    def test_site_spanning_the_origin(self):
        template = Dseqrecord('CCCGTAAAAACGTTTTTGGGGGACGT', circular=True)
        # ACGTCCCGT covers the last 4 and the first 5 bases; ACGGGACGT is its reverse complement
        for sequence, expected_location in (
            ('ACGTCCCGT', 'join(23..26,1..5)'),
            ('ACGGGACGT', 'complement(join(23..26,1..5))'),
        ):
            response = self.annotate(
                [{'id': 2, 'name': 'origin_spanner', 'sequence': sequence}],
                sequence=format_sequence_genbank(template).model_dump(),
                minimal_annealing=9,
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn(expected_location, payload['sequences'][0]['file_content'])
            (entry,) = payload['sources'][0]['annotation_report']
            self.assertEqual((entry['start_location'], entry['end_location']), (22, 31))

    def test_linear_sequence_does_not_wrap(self):
        template = Dseqrecord('CCCGTAAAAACGTTTTTGGGGGACGT', circular=False)
        response = self.annotate(
            [{'id': 2, 'name': 'origin_spanner', 'sequence': 'ACGTCCCGT'}],
            sequence=format_sequence_genbank(template).model_dump(),
            minimal_annealing=9,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(parse_primer_bind_features(payload['sequences'][0]['file_content']), set())

    def test_linear_sequence_finds_ordinary_sites(self):
        # A linear template only loses the sites spanning the origin, the rest are found as usual
        template = Dseqrecord('CCCGTAAAAACGTTTTTGGGGGACGT', circular=False)
        for sequence, strand in (('GTAAAAACGTTTTTG', 1), ('CAAAAACGTTTTTAC', -1)):
            response = self.annotate(
                [{'id': 2, 'name': 'internal', 'sequence': sequence}],
                sequence=format_sequence_genbank(template).model_dump(),
                minimal_annealing=15,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                parse_primer_bind_features(response.json()['sequences'][0]['file_content']),
                {('internal', 3, 18, strand)},
            )

    def test_too_many_binding_sites(self):
        template = Dseqrecord('AT' * 5000, circular=True)
        primers = [{'id': 2, 'name': 'short', 'sequence': 'ATATATATATATAT'}]
        response = self.annotate(primers, sequence=format_sequence_genbank(template).model_dump())
        self.assertEqual(response.status_code, 400)
        self.assertIn('Too many binding sites', response.json()['detail'])

    def test_no_primers(self):
        response = self.annotate([])
        self.assertEqual(response.status_code, 422)


class PrimerBindingSitesThermodynamicsTest(PrimerBindingSitesFixture, unittest.TestCase):
    """Melting temperatures and GC content of the binding sites.

    Every site carries two melting temperatures: that of the stretch which is actually
    bound, and that of the whole primer. They only differ where the primer does not anneal
    over its full length. The GC content is that of the bound stretch alone.
    """

    # The primer concentration the program that produced the reference file feeds to primer3.
    # At the default 50 nM the melting temperatures come out about 3.4 degrees lower.
    reference_settings = {'primer_dna_conc': 500, 'primer_salt_monovalent': 50, 'primer_salt_divalent': 1.5}

    # Read from the reference file. All of these anneal over their whole length, so the two
    # melting temperatures are the same and comparing either one against the reference works.
    reference_melting_temperatures = {
        'M13R': 51.0,
        '(7) 35S_Nuc1F': 61.7,
        '(1) 35S_Inter1F': 62.5,
        'gfp-genomF': 63.3,
        'M13F': 58.4,
        'NPTRgenom': 59.7,
        '(6) 35S_Inter3R': 59.0,
    }

    # Same primers, GC content in percent as the reference file gives it
    reference_gc_content = {
        'M13R': 43.8,
        '(7) 35S_Nuc1F': 47.6,
        '(1) 35S_Inter1F': 47.6,
        'gfp-genomF': 55.0,
        'M13F': 52.9,
        'NPTRgenom': 50.0,
        '(6) 35S_Inter3R': 40.9,
    }

    def test_melting_temperatures_match_the_reference(self):
        response = self.annotate(self.all_primers, settings=self.reference_settings, minimal_annealing=14)
        report = self.report_of(response)
        for name, tm in self.reference_melting_temperatures.items():
            self.assertAlmostEqual(report[name]['melting_temperature'], tm, delta=0.2, msg=name)
            self.assertAlmostEqual(report[name]['primer_melting_temperature'], tm, delta=0.2, msg=name)

    def test_gc_content_matches_the_reference(self):
        response = self.annotate(self.all_primers, minimal_annealing=14)
        report = self.report_of(response)
        for name, gc in self.reference_gc_content.items():
            self.assertAlmostEqual(report[name]['gc_content'] * 100, gc, delta=0.1, msg=name)

    def test_partially_annealing_primer_is_measured_over_the_bound_stretch(self):
        # pAF binds twice: over its whole length, and over its 3'-most 21 bases
        response = self.annotate(self.named('pAF'), settings=self.reference_settings, minimal_annealing=14)
        sites = {
            (entry['start_location'], entry['end_location']): entry
            for entry in response.json()['sources'][0]['annotation_report']
        }

        full = sites[(2207, 2232)]
        self.assertEqual(full['matched_length'], 25)
        self.assertAlmostEqual(full['melting_temperature'], full['primer_melting_temperature'])
        self.assertAlmostEqual(full['gc_content'] * 100, 44.0, delta=0.1)

        # The 4 unpaired bases at the 5' end count towards neither the melting temperature
        # of the duplex nor its GC content, so both are lower than for the whole primer
        partial = sites[(3809, 3830)]
        self.assertEqual(partial['matched_length'], 21)
        self.assertAlmostEqual(partial['melting_temperature'], 59.8, delta=0.2)
        self.assertAlmostEqual(partial['primer_melting_temperature'], 64.9, delta=0.2)
        self.assertAlmostEqual(partial['gc_content'] * 100, 38.1, delta=0.1)

    def test_melting_temperatures_are_written_to_the_genbank(self):
        response = self.annotate(self.named('M13R'), settings=self.reference_settings, minimal_annealing=14)
        genbank = response.json()['sequences'][0]['file_content']
        self.assertIn('Tm: 51.0', genbank)
        self.assertIn('primer Tm: 51.0', genbank)
        self.assertIn('%GC: 43.8', genbank)

    def test_settings_change_the_melting_temperature(self):
        low = self.annotate(self.named('M13R'), settings={'primer_dna_conc': 50}, minimal_annealing=14)
        high = self.annotate(self.named('M13R'), settings=self.reference_settings, minimal_annealing=14)
        self.assertLess(
            self.report_of(low)['M13R']['melting_temperature'],
            self.report_of(high)['M13R']['melting_temperature'],
        )

    def test_minimal_tm_filters_out_the_coldest_sites(self):
        without_filter = self.annotate(self.all_primers, settings=self.reference_settings, minimal_annealing=14)
        with_filter = self.annotate(
            self.all_primers, settings=self.reference_settings, minimal_annealing=14, minimal_tm=60
        )
        kept = self.report_of(with_filter)
        self.assertLess(len(kept), len(self.report_of(without_filter)))
        # M13R melts at 51 degrees, gfp-genomF at 63.2
        self.assertNotIn('M13R', kept)
        self.assertIn('gfp-genomF', kept)
        for entry in kept.values():
            self.assertGreaterEqual(entry['melting_temperature'], 60)
        # A primer whose only site is filtered out is reported as not binding
        self.assertIsNone(
            next(e for e in with_filter.json()['sources'][0]['annotation_report'] if e['primer_name'] == 'M13R')[
                'start_location'
            ]
        )

    def test_minimal_tm_filters_on_the_bound_stretch_not_the_whole_primer(self):
        # The 21 bp site of pAF melts at 59.8, the whole primer at 64.9: filtering at 60
        # must drop that site, and keep only the one where pAF anneals over its full length
        response = self.annotate(
            self.named('pAF'), settings=self.reference_settings, minimal_annealing=14, minimal_tm=60
        )
        self.assertEqual(
            parse_primer_bind_features(response.json()['sequences'][0]['file_content']),
            {('pAF', 2207, 2232, 1)},
        )
