pip install llama-stack-client
llama-stack-client toolgroups register mcp-github --provider-id model-context-protocol --mcp-endpoint "http://github-mcp:8080/"
llama-stack-client toolgroups register mcp-openshift --provider-id model-context-protocol --mcp-endpoint "http://kubernetes-mcp:8080/sse"