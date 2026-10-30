"""Entry point: registers all the tools, adds the download route, and runs the server over HTTP."""

from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import storage
from .app import PORT, mcp

# Importing a tools module registers its tools on `mcp`
from . import tools_strategy  # noqa: F401


@mcp.custom_route('/strategies/{strategy_id}.json', methods=['GET'])
async def download_strategy(request: Request) -> JSONResponse:
    """Plain HTTP route (not an MCP tool) that serves the strategy JSON, see get_strategy_json."""
    try:
        strategy = storage.load_strategy(request.path_params['strategy_id'])
    except ToolError as error:
        return JSONResponse({'detail': str(error)}, status_code=404)
    return JSONResponse(strategy, headers={'Content-Disposition': 'attachment; filename="cloning_strategy.json"'})


def main():
    mcp.run('streamable-http', port=PORT, stateless_http=True)


if __name__ == '__main__':
    main()
