"""Entry point: registers all the tools, adds the download and upload routes, and runs the server over HTTP."""

from pathlib import Path

import uvicorn
from mcp.server.mcpserver.exceptions import ToolError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from . import cloning_api, names, storage
from .app import PORT, mcp
from .products import add_product_to_strategy

# Importing a tools module registers its tools on `mcp`
from . import tools_genome, tools_import, tools_operations, tools_primers, tools_strategy  # noqa: F401


@mcp.custom_route('/strategies/{strategy_id}.json', methods=['GET'])
async def download_strategy(request: Request) -> JSONResponse:
    """Plain HTTP route (not an MCP tool) that serves the strategy JSON, see get_strategy_json."""
    try:
        strategy = storage.load_strategy(request.path_params['strategy_id'])
    except ToolError as error:
        return JSONResponse({'detail': str(error)}, status_code=404)
    return JSONResponse(strategy, headers={'Content-Disposition': 'attachment; filename="cloning_strategy.json"'})


UPLOAD_FORM = """<!doctype html>
<title>Upload a sequence file</title>
<h1>Upload a sequence file to OpenCloning</h1>
<p>GenBank, FASTA, EMBL or SnapGene (.dna). The first sequence of each file is added to the strategy.</p>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" multiple required>
  <button type="submit">Upload</button>
</form>
"""


@mcp.custom_route('/strategies/{strategy_id}/upload', methods=['GET'])
async def upload_form(request: Request) -> HTMLResponse:
    """A web page to upload a file without passing it through the model, see get_upload_link."""
    return HTMLResponse(UPLOAD_FORM)


@mcp.custom_route('/strategies/{strategy_id}/upload', methods=['POST'])
async def upload_file(request: Request) -> HTMLResponse:
    """Add the first sequence of each uploaded file to the strategy. Only the happy path for now."""
    files = (await request.form()).getlist('file')
    contents = [await file.read() for file in files]

    def add_first_sequences():
        added = []
        for file, content in zip(files, contents):
            # Named after the file: SnapGene files often have no name inside
            name = names.clean(Path(file.filename).stem)
            result = cloning_api.post(
                '/read_from_file', files={'file': (file.filename, content)}, params={'output_name': name}
            )
            added.append(
                add_product_to_strategy(request.path_params['strategy_id'], result, product_index=0)['sequence']
            )
        return added

    # The storage and the cloning API calls are blocking, keep them off the event loop
    sequences = await run_in_threadpool(add_first_sequences)
    items = ''.join(f'<li><b>{s["name"]}</b> ({s["length"]} bp): sequence {s["id"]}</li>' for s in sequences)
    return HTMLResponse(f'<p>Added:</p><ul>{items}</ul><p>You can go back to the assistant.</p>')


def app():
    """Factory for uvicorn, which needs it to reload on code changes (see the README)."""
    return mcp.streamable_http_app(stateless_http=True)


def main():
    # Not mcp.run(): it can't set a shutdown timeout, and MCP clients keep a streaming connection open,
    # so Ctrl+C would wait for them forever
    uvicorn.run('opencloning_mcp.server:app', factory=True, port=PORT, timeout_graceful_shutdown=2)


if __name__ == '__main__':
    main()
