# generator_calc

A Python project for generating and/or parsing calculator expressions, built around JupyterLab notebooks.

## Environment

- Python virtual environment at `.venv/` — always activate before running Python:
  ```bash
  source .venv/bin/activate
  ```
- JupyterLab is the primary interface: `jupyter lab`
- Dependencies are pinned in `requirements.txt`; install with `pip install -r requirements.txt`

## Key dependencies

- `lark` — grammar-based expression parser
- `numpy`, `pandas`, `scipy` — numerical computation
- `matplotlib` — plotting
- `jupyterlab` — notebook environment

## Adding dependencies

Pin exact versions in `requirements.txt` (the file already uses `==` pinning). After installing a new package, update the file:
```bash
pip freeze > requirements.txt
```
