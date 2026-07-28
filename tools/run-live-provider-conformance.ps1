[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("llamacpp", "vllm", "ollama")]
    [string]$Provider
)

$ErrorActionPreference = "Stop"

& uv run python .\tools\run_live_provider_conformance.py --provider $Provider
exit $LASTEXITCODE
