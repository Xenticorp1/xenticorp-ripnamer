#!/usr/bin/env bash
# Sets up Azure Artifact Signing for the Tauri build (Windows runner, bash).
# Needs the repository secrets AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET,
# AZURE_SIGNING_ENDPOINT, AZURE_SIGNING_ACCOUNT and AZURE_SIGNING_PROFILE passed in as env.
# Outputs: signed=true|false, config=<tauri config file that adds the signCommand>.
# The signCommand makes Tauri sign the app exe, the NSIS uninstaller and the installer.
# Without the secrets the build stays unsigned, unless REQUIRE_SIGNING=true (then it fails).
set -euo pipefail

missing=""
for v in AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET AZURE_SIGNING_ENDPOINT \
  AZURE_ARTIFACT_SIGNING_ACCOUNT AZURE_ARTIFACT_SIGNING_CERTIFICATE_PROFILE; do
  [ -n "${!v:-}" ] || missing="$missing $v"
done
if [ -n "$missing" ]; then
  if [ "${REQUIRE_SIGNING:-false}" = "true" ]; then
    echo "::error::Code signing is required here but these are empty:$missing (check the repository secrets)."
    exit 1
  fi
  echo "::warning::Code signing secrets not set ($missing ); this build is unsigned."
  echo "signed=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Pinned signing tool (github.com/levminer/trusted-signing-cli, release 0.12.0) and its checksum.
version="0.12.0"
sha="dd6fa95a0367cbd32ea520037c3df72d1ed8f523a5b07883b0c2a4034e918a53"
dir="$RUNNER_TEMP/signing"
mkdir -p "$dir"
curl -fsSL -o "$dir/artifact-signing-cli.exe" \
  "https://github.com/levminer/trusted-signing-cli/releases/download/${version}/artifact-signing-cli.exe"
echo "${sha}  $dir/artifact-signing-cli.exe" | sha256sum -c -
echo "$dir" >> "$GITHUB_PATH"

# The tool logs in with `az login --service-principal`, which fails with "No subscriptions found"
# because the signing identity only has a role on the signing account. Signing doesn't need a
# subscription, so point the tool at a wrapper that adds --allow-no-subscriptions.
az_real='C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
wrap="$(cygpath -w "$dir")\\az-wrap.cmd"
printf '@echo off\r\ncall "%s" %%* --allow-no-subscriptions\r\n' "$az_real" > "$dir/az-wrap.cmd"
echo "AZURE_CLI_PATH=$wrap" >> "$GITHUB_ENV"

node -e '
  const cmd = "artifact-signing-cli -e " + process.env.AZURE_SIGNING_ENDPOINT + " %1";
  require("fs").writeFileSync(process.argv[1], JSON.stringify({ bundle: { windows: { signCommand: cmd } } }));
' "$dir/sign.json"
echo "config=$dir/sign.json" >> "$GITHUB_OUTPUT"
echo "signed=true" >> "$GITHUB_OUTPUT"
