"""Tools to create a strategy, look at it, and export it."""

from . import storage
from .app import BASE_URL, mcp


@mcp.tool()
def start_strategy(description: str = '') -> dict:
    """Start a new, empty cloning strategy. Call this before any other tool.

    Returns a strategy_id: pass it to every other tool. To build several independent strategies,
    call this once per strategy.
    """
    strategy_id = storage.create_strategy(description)
    return {'strategy_id': strategy_id}


@mcp.tool()
def describe_strategy(strategy_id: str) -> dict:
    """List the sequences and primers in the strategy, and how each sequence was made.

    For each sequence, `made_by` gives the type of step that produced it and the ids of its inputs.
    Use this to find ids, or to check the state of the strategy before the next step.
    """
    strategy = storage.load_strategy(strategy_id)
    sources_by_id = {source['id']: source for source in strategy['sources']}
    sequences = []
    for sequence in strategy['sequences']:
        source = sources_by_id[sequence['id']]
        sequences.append(
            {
                'id': sequence['id'],
                'made_by': {'type': source['type'], 'input_ids': [i['sequence'] for i in source['input']]},
            }
        )
    primers = [{'id': p['id'], 'name': p['name'], 'sequence': p['sequence']} for p in strategy['primers']]
    return {'description': strategy['description'], 'sequences': sequences, 'primers': primers}


@mcp.tool()
def get_strategy_json(strategy_id: str) -> dict:
    """Get a link to download the strategy as an OpenCloning JSON file.

    Give the link to the user: they can open the file in the OpenCloning web app, where every step
    of the strategy can be inspected and edited.
    """
    strategy = storage.load_strategy(strategy_id)
    return {
        'download_url': f'{BASE_URL}/strategies/{strategy_id}.json',
        'number_of_sequences': len(strategy['sequences']),
        'number_of_primers': len(strategy['primers']),
    }
