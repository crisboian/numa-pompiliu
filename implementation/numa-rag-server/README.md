"""NUMA RAG Server — MCP-based hybrid retrieval server.

Usage:
    # Start the MCP server (stdio transport):
    python -m numa_rag.server

    # Or via the entry point:
    python -m implementation.numa_rag_server

    # Test with a query:
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kgaa_search","arguments":{"query":"Can the K-700 operate at 195°?"}}}' | python -m numa_rag.server
"""
