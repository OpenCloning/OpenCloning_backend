from pydna.parsers import parse
from Bio.SeqIO import parse as bio_parse
from opencloning.dna_utils import align_sanger_traces

with open('TN9W63_4_pREX0010.ab1', 'rb') as f:
    trace = next(bio_parse(f, 'abi'))

seq = parse('pREX0008_rc.gb')[0]

aligned = align_sanger_traces(seq, [str(trace.seq)])
print(*aligned, sep='\n')
