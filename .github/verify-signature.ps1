# Fails unless every given file has a valid Authenticode signature. Prints who signed each one.
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Files)
$bad = 0
foreach ($f in $Files) {
  $s = Get-AuthenticodeSignature -FilePath $f
  $who = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { "(no signer)" }
  $ts = if ($s.TimeStamperCertificate) { "timestamped" } else { "NOT timestamped" }
  Write-Output ("{0}: {1}, {2}, {3}" -f (Split-Path $f -Leaf), $s.Status, $ts, $who)
  if ($s.Status -ne "Valid" -or -not $s.TimeStamperCertificate) { $bad++ }
}
if ($bad -gt 0) { Write-Error "$bad file(s) not properly signed"; exit 1 }
