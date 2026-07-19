param(
    [string]$Narration = "docs\demo-narration.txt",
    [string]$Output = "artifacts\conglomeraite-demo-narration.wav",
    [string]$VoiceName = "Microsoft Mark",
    [ValidateRange(-10, 10)]
    [int]$Rate = 0
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $installed = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled })
    $selected = $installed | Where-Object { $_.VoiceInfo.Name -eq $VoiceName } | Select-Object -First 1
    if (-not $selected) {
        $selected = $installed | Where-Object { $_.VoiceInfo.Gender -eq "Male" } | Select-Object -First 1
    }
    if (-not $selected) {
        throw "No enabled male speech voice is installed."
    }

    $synth.SelectVoice($selected.VoiceInfo.Name)
    $synth.Rate = $Rate
    $synth.Volume = 100
    $text = Get-Content -Raw -LiteralPath $Narration
    $resolvedOutput = [System.IO.Path]::GetFullPath($Output)
    [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($resolvedOutput)) | Out-Null
    $synth.SetOutputToWaveFile($resolvedOutput)
    $synth.Speak($text)
    [pscustomobject]@{
        Voice = $selected.VoiceInfo.Name
        Gender = $selected.VoiceInfo.Gender.ToString()
        Rate = $Rate
        Output = $resolvedOutput
    }
}
finally {
    $synth.Dispose()
}
