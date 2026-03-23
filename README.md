# ARPES Converter (Browser-Based)

A lightweight, browser-based tool for ARPES data format conversion.
This project was developed as a personal practice project for web interface design and scientific data handling.

---

## Demo

![screenshot](./docs/screenshot.png)

Live Demo: https://your-demo-link.com

---

## Features

* `.ibw` → `.npz`
* `.itx` → `.npz`
* `.pxt` → `.npz`
* `.zip` → `.npz` (batch support)
* `.npz` → `.nc` (xarray / NetCDF)

Additional capabilities:

* Metadata input and embedding
* Axis reconstruction (`axis_0`, `axis_1`)
* Fully client-side processing (no backend)

---

## Notes

* Recommended file size: ≤ 100 MB
* Hard limit: ≤ 1 GB
* Large files may be slower due to browser memory limits

---

## Disclaimer

This project is developed by a graduate student for web interface practice and scientific tool development.

If any content is found to infringe intellectual property rights, please contact me and it will be removed promptly.

---

## Third-Party Libraries

* Pyodide — https://pyodide.org/
* NumPy — https://numpy.org/
* xarray — https://docs.xarray.dev/

---

## License

MIT License
