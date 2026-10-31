# Eval tasks for the MCP server

These are the tasks to try with a real model driving the tools, to find out where the tool
descriptions, the server instructions and the error messages are not good enough.

Run them with the server running (`uv run opencloning-mcp`) and the tools connected
(`claude mcp add --transport http opencloning http://localhost:8002/mcp`), in a **separate session**
from the one that wrote the code: a session that knows the implementation is not a fair test.

For each task, record what the model did, where it went wrong, and what was changed in response.
Fix **docstrings, the `INSTRUCTIONS` in `app.py` and error messages** on this evidence, not on
intuition. That, rather than new tools, is what makes the server drivable.

## What to watch for in every task

- Does it call `start_strategy` first and reuse the `strategy_id`?
- When a tool answers `"choose_product"`, does it pick on the evidence in the candidates (length,
  ends, topology), or does it guess, or does it ask the user?
- Does it invent sequence ids, or look them up with `describe_strategy`?
- Does it pass sensible `name` arguments, and tell the user the names it chose?
- Does it offer the download link at the end without being asked?

## 1. Digest and ligate

**Prompt:** paste the GenBank of `pFA6a-hphMX6.gb`, then:

> Cut out the hphMX6 cassette from this plasmid with BamHI and SacI and put this gene in its place:
> *(paste a few hundred bases of a gene)*. Design the primers you need.

**Expected:** two primers with BamHI / SacI tails, a PCR of the gene, a digest of the plasmid keeping
the ~2.5 kb backbone, a digest of the PCR product, and a circular ligation of about 2.6 kb.

**Watch:** whether it chooses the backbone fragment rather than the cassette, and whether it digests
the PCR product before ligating.

## 2. PCR and Gibson

**Prompt:** two sequences, with the instruction to amplify each with primers carrying tails that
overlap the other fragment, and assemble them into a circular plasmid.

**Expected:** two PCRs, then `gibson_assembly` with `circular_only=True`.

**Watch:** whether it uses `circular_only`, and whether it understands that the order of
`sequence_ids` does not matter.

## 3. Golden Gate

**Prompt:** the four fragments of `test_endpoints_assembly.py::test_golden_gate` (three linear BsaI
parts and the circular backbone), asking for a Golden Gate assembly with BsaI.

**Expected:** one call to `restriction_and_ligation` with `enzymes=["BsaI"]` and
`circular_only=True`, giving a single 39 bp circular product.

**Watch:** whether it reaches for `restriction_digest` + `ligation` separately instead of the
one-pot tool.

## 4. Gateway BP then LR

The hardest task, and the most informative. Uses the SnapGene files in
`packages/opencloning/tests/test_files/gateway_manual_cloning/`. They are binary, so the model
cannot pass them as text: it should call `get_upload_link`, and you upload the three files together in
the browser (the form takes several).

**Prompt:** `pDONRtm221` and `pcr_product-attP1_1-attP2_1` for a BP reaction, then the entry clone
and `pET-53-DESTtm` for an LR reaction.

**Expected:** a 4790 bp circular entry clone (with `circular_only=True` the BP gives exactly one
product), then the 7423 bp expression clone chosen out of 4 LR candidates.

**Watch:** whether it picks BP and LR correctly (`list_gateway_sites` is there to check), whether it
uses `circular_only`, and above all **how it chooses among the 4 LR candidates** — this is the test
of whether the candidate summaries carry enough information. Also watch whether it asks you to
upload the files, waits for you, and then finds the new ids with `describe_strategy`.

## 5. Homologous recombination

**Prompt:** a linear locus and a cassette sharing homology arms with it, asking for an integration by
homologous recombination.

**Expected:** `homologous_recombination` with the template first and the insert second.

**Watch:** the argument order (it is `template_id`, `insert_id`, and getting it wrong changes the
result), and whether it lowers `minimal_homology` when the arms are short.

## 6. Recovery from a vague reference

**Prompt:** after any of the tasks above, refer to a sequence by name rather than by id, e.g.
*"digest the backbone again, this time with EcoRI"*.

**Expected:** a call to `describe_strategy` to find the id, then the digest.

**Watch:** whether it guesses an id. If it does, the error message from `storage.get_by_id` lists the
valid ids, so note whether it recovers from that on its own.

## 7. Gene from a genome

**Prompt:** *"Get the gene cdc2 from S. pombe with 1 kb on each side, and design primers to amplify just the
coding region."* (Then try *"now the gene cdc3"*, which is on the minus strand.)

**Expected:** `find_genome_assembly` (reference assembly `GCF_000002945.2`), `find_gene`, then
`add_genome_region_from_gene` with the default 1000 bp flanks, giving a 3888 bp sequence.

**Watch:** whether it asks when the species or the gene is ambiguous instead of guessing; whether it passes
the locus tag; and whether it understands that the product of a minus-strand gene is already oriented as the
gene, so upstream flank comes first.

## Results

Fill in as the tasks are run: one short section per task with what the model did, what went wrong,
and the change made in response.
