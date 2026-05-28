$body = @{
    repo_url = "https://github.com/expressjs/express-starter"
    api_key = ""
    execution_mode = "simulated"
    simulation_behavior = "fail-and-fix"
} | ConvertTo-Json

Write-Host "Triggering DockerForge Agent (Simulated Fail & Fix)..."
$response = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/forge" -Body $body -ContentType "application/json"
$taskId = $response.task_id
Write-Host "Task ID created: $taskId"
Write-Host "Listening to Server-Sent Events stream..."
Write-Host "--------------------------------------------------"

# Read SSE Stream
$streamUrl = "http://127.0.0.1:8000/api/stream/$taskId"
$request = [System.Net.WebRequest]::Create($streamUrl)
$response = $request.GetResponse()
$reader = New-Object System.IO.StreamReader($response.GetResponseStream())

while (-not $reader.EndOfStream) {
    $line = $reader.ReadLine()
    if ($line -and $line.StartsWith("data: ")) {
        $jsonStr = $line.Substring(6)
        $data = ConvertFrom-Json $jsonStr
        
        if ($data.type -eq "log") {
            $logType = $data.log.type.ToUpper()
            $text = $data.log.text
            if ($logType -eq "AGENT") {
                Write-Host "[Agent] $text" -ForegroundColor Magenta
            } elseif ($logType -eq "ERROR") {
                Write-Host "[Error] $text" -ForegroundColor Red
            } elseif ($logType -eq "SUCCESS") {
                Write-Host "[Success] $text" -ForegroundColor Green
            } elseif ($logType -eq "WARN") {
                Write-Host "[Warning] $text" -ForegroundColor Yellow
            } else {
                Write-Host "        $text"
            }
        } elseif ($data.type -eq "step") {
            Write-Host ">> STEP UPDATE: $($data.step.id) = $($data.step.status)" -ForegroundColor Cyan
        } elseif ($data.type -eq "result") {
            Write-Host "--------------------------------------------------"
            Write-Host "RESULT: $($data.status.ToUpper())" -ForegroundColor Green
            if ($data.status -eq "success") {
                Write-Host "Dockerfile Excerpt (First 5 lines):"
                $lines = $data.dockerfile -split "`n"
                for ($i = 0; $i -lt [Math]::Min(5, $lines.Length); $i++) {
                    Write-Host "  $($lines[$i])" -ForegroundColor DarkGray
                }
            }
        }
    }
}

$reader.Close()
$response.Close()
