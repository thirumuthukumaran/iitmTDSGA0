# Acme Appliances Ledger Agent

FastAPI service with `POST /` and `POST /ask` accepting `{"question":"..."}` and returning `{"answer": ...}`.

## Deploy
Push `main.py`, `requirements.txt`, and `render.yaml` to GitHub, then create a Render Blueprint from the repository. The grader URL should be the public HTTPS service URL, preferably with `/`.

## Important
The service discovers API resources advertised by the exam `questionData` entry point and uses a lightweight rule-based query layer. Before submission, test the API's actual response shape and confirm the discovered records cover orders, refunds, products, and customers. This environment could not reach the exam host during package creation, so the discovery logic may need adjustment if the API uses undocumented navigation patterns or requires query parameters for child routes.
