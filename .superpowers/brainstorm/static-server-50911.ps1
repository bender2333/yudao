$root = 'C:\project\yudao\.superpowers\brainstorm\stable-long-1779935537\content'
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add('http://127.0.0.1:50911/')
$listener.Prefixes.Add('http://localhost:50911/')
$listener.Start()
while ($listener.IsListening) {
  try {
    $ctx = $listener.GetContext()
    $rel = [Uri]::UnescapeDataString($ctx.Request.Url.AbsolutePath.TrimStart('/'))
    if ([string]::IsNullOrWhiteSpace($rel)) { $rel = 'dynamic-workflow-generation-boundary.html' }
    $path = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $ctx.Response.StatusCode = 404; $bytes = [Text.Encoding]::UTF8.GetBytes('Not found') }
    else { $ctx.Response.StatusCode = 200; $ctx.Response.ContentType = 'text/html; charset=utf-8'; $bytes = [IO.File]::ReadAllBytes($path) }
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.Close()
  } catch { }
}
