from pydna.utils import location_boundaries
from ...pydantic_models import BaseCloningStrategy
from opencloning_linkml.datamodel import (
    Primer as PrimerModel,
    PCRSource,
    HomologousRecombinationSource,
)
from pydna.parsers import parse as pydna_parse
import os
import json
from pydna import tm
from Bio.Seq import reverse_complement
import argparse
from Bio.SeqFeature import Location

chromosomes = {
    'NC_003424.3': 'I',
    'NC_003423.3': 'II',
    'NC_003421.2': 'III',
    'NC_088682.1': 'MT',
}


def find_primer_aligned_sequence(pcr_sources: list[PCRSource], primer: PrimerModel) -> str:
    for source in pcr_sources:
        if source.input[0].sequence == primer.id:
            loc = Location.fromstring(source.input[0].right_location)
            return loc.extract(primer.sequence)
        if source.input[-1].sequence == primer.id:
            loc = Location.fromstring(source.input[-1].left_location)
            return loc.extract(reverse_complement(primer.sequence))
    raise ValueError(f"Primer {primer.id} not found in any PCR source")


def process_folder(working_dir: str):
    with open(os.path.join(working_dir, 'cloning_strategy.json'), 'r') as f:
        strategy = BaseCloningStrategy.model_validate(json.load(f))

    pcr_sources = [s for s in strategy.sources if s.type == 'PCRSource']
    # We do this to have action to .end and .start
    pcr_sources = [PCRSource.model_validate(s.model_dump()) for s in pcr_sources]
    locus_source = next(s for s in strategy.sources if s.type == 'GenomeCoordinatesSource')
    locus_location = Location.fromstring(locus_source.coordinates)
    hrec_source = next(s for s in strategy.sources if s.type == 'HomologousRecombinationSource')
    # We do this to have action to .end and .start
    hrec_source: HomologousRecombinationSource = HomologousRecombinationSource.model_validate(hrec_source.model_dump())

    chromosome = chromosomes[locus_source.repository_id]
    insertion_start = (
        locus_location.start + location_boundaries(Location.fromstring(hrec_source.input[0].right_location))[1]
    )
    insertion_end = (
        locus_location.start + location_boundaries(Location.fromstring(hrec_source.input[-1].left_location))[0]
    )

    # Write out the sequences in genbank format and extract some relevant info
    sequences = [pydna_parse(sequence.file_content)[0] for sequence in strategy.sequences]
    for seq in sequences:
        with open(os.path.join(working_dir, f"{seq.name}.gb"), 'w') as f:
            f.write(seq.format('genbank'))

        if seq.name == 'amplified_marker':
            amplified_marker_length = len(seq.seq)

        if seq.name == 'check_pcr_left':
            check_pcr_left_length = len(seq.seq)

        if seq.name == 'check_pcr_right':
            check_pcr_right_length = len(seq.seq)

    primer_dict = dict()

    primer_names = ['primer_fwd_check', 'primer_fwd', 'primer_rvs', None, 'primer_rvs_check', None]
    for i, primer in enumerate(strategy.primers):
        if primer_names[i] is None:
            continue
        name = primer_names[i]
        primer_dict[name] = primer.sequence
        primer_dict[name + '_name'] = primer.name
        # Find what the alignment bit of the primer is
        aligned_seq = find_primer_aligned_sequence(pcr_sources, primer)
        if 'rvs' in name:
            aligned_seq = reverse_complement(aligned_seq)
        primer_dict[name + '_bound'] = aligned_seq
        primer_dict[name + '_tm'] = tm.tm_default(aligned_seq)

    metadata_path = os.path.join(working_dir, 'metadata.json')
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

    summary = {
        'gene': os.path.basename(working_dir),
        'cloning_type': metadata.get('cloning_type', 'gene_deletion'),
        'allele_name': metadata.get('allele_name'),
        'chromosome': chromosome,
        'insertion_start': insertion_start,
        'insertion_end': insertion_end,
        'amplified_marker_length': amplified_marker_length,
        'check_pcr_left_length': check_pcr_left_length,
        'check_pcr_right_length': check_pcr_right_length,
    }

    summary.update(primer_dict)

    with open(os.path.join(working_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=4)


def main(input_dir: str):
    for folder in os.listdir(input_dir):
        working_dir = os.path.join(input_dir, folder)
        if not os.path.isdir(working_dir):
            continue
        if not os.path.exists(os.path.join(working_dir, 'cloning_strategy.json')):
            print(f"Skipping {folder}: no cloning_strategy.json found")
            continue
        process_folder(working_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process cloning strategies and generate summaries')
    parser.add_argument(
        '--input_dir', type=str, default='batch_cloning_output', help='Input directory containing gene folders'
    )
    args = parser.parse_args()

    main(args.input_dir)
