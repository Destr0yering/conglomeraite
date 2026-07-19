param(
    [string]$Narration = "docs\demo-narration.txt",
    [string]$Output = "artifacts\conglomeraite-demo-narration.wav",
    [string]$VoiceName = "en-US-AndrewNeural",
    [string]$Rate = "+3%",
    [string]$Python = "python",
    [string]$Ffmpeg = ""
)

$ErrorActionPreference = "Stop"
$text = Get-Content -Raw -LiteralPath $Narration
$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($resolvedOutput)) | Out-Null
$temporaryMp3 = [System.IO.Path]::ChangeExtension($resolvedOutput, ".neural.mp3")

try {
    if (-not $Ffmpeg) {
        $Ffmpeg = (& $Python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
        if ($LASTEXITCODE -ne 0 -or -not $Ffmpeg) {
            throw "Unable to locate FFmpeg through imageio-ffmpeg. Install the demo dependencies first."
        }
    }

    & $Python -m edge_tts --voice $VoiceName ("--rate={0}" -f $Rate) --text $text --write-media $temporaryMp3
    if ($LASTEXITCODE -ne 0) {
        throw "Online neural narration failed for voice $VoiceName."
    }

    & $Ffmpeg -hide_banner -loglevel error -y -i $temporaryMp3 -af "loudnorm=I=-16:TP=-1.5:LRA=11" -ac 1 -ar 48000 -c:a pcm_s16le $resolvedOutput
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg failed to normalize the neural narration."
    }

    [pscustomobject]@{
        Provider = "Microsoft online neural speech"
        Voice = $VoiceName
        Rate = $Rate
        Output = $resolvedOutput
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryMp3) {
        Remove-Item -LiteralPath $temporaryMp3
    }
}
