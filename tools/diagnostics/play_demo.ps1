param([string]$Text = '今日は日本語の字幕を見ながら勉強します。', [switch]$GenerateOnly)
Add-Type -AssemblyName System.Speech
$taskCaptionRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $taskSynth.SelectVoice('Microsoft Haruka Desktop')
    $taskSynth.Rate = -1
    $taskSynth.SetOutputToWaveFile((Join-Path $taskCaptionRoot 'logs\demo-ja.wav'))
    $taskEscapedText = [System.Security.SecurityElement]::Escape($Text)
    # Keep loopback active long enough for Tiger's silence detector to finalize.
    $taskSynth.SpeakSsml('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ja-JP">' + $taskEscapedText + '<break time="2000ms"/></speak>')
    $taskSynth.SetOutputToNull()
} finally { $taskSynth.Dispose() }
if ($GenerateOnly) { return }
$taskPlayer = New-Object System.Media.SoundPlayer (Join-Path $taskCaptionRoot 'logs\demo-ja.wav')
$taskPlayer.PlaySync()
