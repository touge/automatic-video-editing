# 声明变量，使用 $ 符号
$GEMINI_API_KEY = "gemini-litouge" # 替换为你的 Gemini API Key
$BASE_URL = "http://127.0.0.1:10001"

$TEXT_PATH = "tasks\yt-xovle1A57wo\manuscript.txt" # 替换为你的文本文件路径
$DISPLAY_NAME = "TEXT"

$tmp_header_file = "tasks\yt-xovle1A57wo\upload-header.tmp"
$response_file = "tasks\yt-xovle1A57wo\response.json"
$file_info_file = "tasks\yt-xovle1A57wo\file_info.json"

# --- 步骤 1: 获取上传 URL ---
Write-Host ">>> Step 1: Getting upload URL..."
try {
    # 使用 Invoke-WebRequest 发送初始请求
    # -PassThru 参数让命令返回完整的响应对象，而不是只返回网页内容
    $response = Invoke-WebRequest -Uri "$($BASE_URL)/upload/v1beta/files?key=$($GEMINI_API_KEY)" `
        -Method POST `
        -Headers @{
            "X-Goog-Upload-Protocol" = "resumable";
            "X-Goog-Upload-Command" = "start";
            "X-Goog-Upload-Header-Content-Length" = (Get-Item $TEXT_PATH).Length;
            "X-Goog-Upload-Header-Content-Type" = (Get-Item $TEXT_PATH).Extension;
            "Content-Type" = "application/json"
        } `
        -Body "{'file': {'display_name': 'TEXT'}}" `
        -PassThru

    # 直接从响应对象的 Headers 属性中获取上传 URL，这比读取文件更可靠
    $upload_url = $response.Headers."X-Goog-Upload-URL"

    if ([string]::IsNullOrEmpty($upload_url)) {
        Write-Error "Error: The upload URL could not be retrieved from the response headers."
        Write-Error "This could be an issue with the proxy server or API key."
        exit
    }
    Write-Host "Success! Upload URL received."
}
catch {
    Write-Error "Error during initial upload request. Check your proxy and network settings."
    Write-Error "Error message: $($_.Exception.Message)"
    exit
}