[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("llamacpp", "vllm", "ollama")]
    [string]$Provider
)

$ErrorActionPreference = "Stop"

$profiles = @{
    llamacpp = @{
        Test = "tests/integration/test_llamacpp_live.py"
        Required = @("AIDN_LLAMACPP_ENDPOINT", "AIDN_LLAMACPP_MODEL")
        EnableVariable = "AIDN_LLAMACPP_LIVE"
    }
    vllm = @{
        Test = "tests/integration/test_vllm_live.py"
        Required = @("AIDN_VLLM_ENDPOINT", "AIDN_VLLM_MODEL")
    }
    ollama = @{
        Test = "tests/integration/test_ollama_live.py"
        Required = @("AIDN_OLLAMA_ENDPOINT", "AIDN_OLLAMA_MODEL")
    }
}

$profile = $profiles[$Provider]
foreach ($variable in $profile.Required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($variable))) {
        throw "Set $variable before running the $Provider live conformance profile."
    }
}

if ($profile.EnableVariable) {
    [Environment]::SetEnvironmentVariable($profile.EnableVariable, "1", "Process")
}

Write-Host "Running $Provider live-provider conformance: $($profile.Test)"
& uv run pytest -q $profile.Test --no-cov
exit $LASTEXITCODE
