# Exam `solve_challenge` MCP server

This service implements an MCP Streamable HTTP endpoint at `/mcp` and exposes exactly one tool: `solve_challenge`.

For every `tools/call`, it reads `X-Exam-Challenge` from that specific HTTP request's headers and returns the first 16 lowercase hex characters of:

`SHA-256("<challenge>:24f3002203@ds.study.iitm.ac.in")`

The tool schema has no required properties. The request body is not used to obtain the challenge.

## Deploy publicly on Render

1. Extract this ZIP.
2. Push the files (`main.py`, `requirements.txt`, `render.yaml`, etc.) into a GitHub repository. You can use your existing `iitmTDSGA0` repository if that is where you are keeping the assignment, or create a separate repository.
3. Open Render and choose **New + → Blueprint** (or create a **Web Service** connected to the repository).
4. If using Blueprint, select the repository containing `render.yaml` and apply it. If creating a Web Service manually, use:
   - Runtime: Python
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Wait until the service is live. Your MCP endpoint is `https://YOUR-SERVICE.onrender.com/mcp`; the health check is `https://YOUR-SERVICE.onrender.com/health`.
6. Submit the full HTTPS URL ending in `/mcp` to the grader, not the health URL.

Free instances may sleep when idle. Make sure the first grading request can wake the service and that the service remains deployed through the deadline.

## Quick local check

```bash
python -m pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal, check health:

```bash
curl http://127.0.0.1:8000/health
```

Check the tool list:

```bash
curl -s http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Check a tool call (example challenge only):

```bash
curl -s http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -H 'X-Exam-Challenge: 0123456789abcdef0123456789abcdef' \
  -H 'X-Exam-Timestamp: 1790000000000' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"solve_challenge","arguments":{}}}'
```

The timestamp and signature are optional for this assignment's scoring; the challenge header is required and used directly.
