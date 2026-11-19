'''Minimal MCP client: connect to mcp_server/server.py, list capabilities and call the tools.

Run from the project root:  python mcp_server/client_demo.py
'''

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.types import TextContent, TextResourceContents

SERVER = StdioServerParameters(
    command=sys.executable,
    args=[str(Path(__file__).with_name('server.py'))],
)


async def main() -> None:
    # Entering the block spawns the subprocess and negotiates; leaving it shuts it down.
    async with Client(SERVER) as client:
        name = client.server_info.name if client.server_info else 'unknown'
        print('Connected to:', name)
        print()

        # ---- Tools ----------------------------------------------------------
        listed = await client.list_tools()
        print(f'Tools available ({len(listed.tools)}):')
        for tool in listed.tools:
            print(f'  - {tool.name}: {tool.description.splitlines()[0]}')
        print()

        # ---- Resources ------------------------------------------------------
        read = await client.read_resource('devkb://catalog')
        print('Catalog:')
        for contents in read.contents:
            if isinstance(contents, TextResourceContents):
                print(contents.text)
        print()

        # ---- Prompts --------------------------------------------------------
        prompts = await client.list_prompts()
        print('Prompts:', [prompt.name for prompt in prompts.prompts])
        rendered = await client.get_prompt('troubleshoot_error', {'error_message': 'QueuePool limit of size 5 overflow 10 reached'})
        for message in rendered.messages:
            if isinstance(message.content, TextContent):
                print(f'  [{message.role}] {message.content.text[:160]}...')
        print()

        # ---- Calling tools --------------------------------------------------
        answer = await client.call_tool(
            'ask_dev_assistant', {'question': 'How do we handle database connection pool exhaustion?'}
        )
        print('ask_dev_assistant ->', answer.structured_content)
        print()

        snippets = await client.call_tool('search_code_snippets', {'query': 'retry with exponential backoff', 'language': 'python', 'k': 1})
        first = (snippets.structured_content or {}).get('results', [{}])[0]
        print('search_code_snippets ->', first.get('doc_id'), '|', first.get('title'))
        print()

        unknown = await client.call_tool('ask_dev_assistant', {'question': 'What is the capital city of Mars?', 'max_attempts': 1})
        print('Out-of-scope question ->', (unknown.structured_content or {}).get('status'))


if __name__ == '__main__':
    asyncio.run(main())
