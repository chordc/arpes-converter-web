console.log("APP_JS_BUILD_HTML_LOCKED_SYNC_RESULT_PANEL");

const RECOMMENDED_SIZE_BYTES = 100 * 1024 * 1024;   // 100 MB
const HARD_LIMIT_BYTES = 1024 * 1024 * 1024;        // 1 GB

const fileInput = document.getElementById("fileInput");
const chooseFileBtn = document.getElementById("chooseFileBtn");
const uploadDropzone = document.getElementById("uploadDropzone");

const inputFormatSelect = document.getElementById("inputFormatSelect");
const outputFormatSelect = document.getElementById("outputFormatSelect");

const convertBtn = document.getElementById("convertBtn");
const logBox = document.getElementById("logBox");
const metaBox = document.getElementById("metaBox");
const downloadLink = document.getElementById("downloadLink");

const axisLabelsInput = document.getElementById("axisLabelsInput");
const axisUnitsInput = document.getElementById("axisUnitsInput");
const experimentDateInput = document.getElementById("experimentDateInput");
const locationInput = document.getElementById("locationInput");
const hvInput = document.getElementById("hvInput");
const slitInput = document.getElementById("slitInput");

const sampleNameInput = document.getElementById("sampleNameInput");
const operatorInput = document.getElementById("operatorInput");
const temperatureInput = document.getElementById("temperatureInput");
const polarizationInput = document.getElementById("polarizationInput");
const notesInput = document.getElementById("notesInput");

const metadataModeSelect = document.getElementById("metadataModeSelect");
const outputNameInput = document.getElementById("outputNameInput");

const customMetadataList = document.getElementById("customMetadataList");
const addCustomMetadataBtn = document.getElementById("addCustomMetadataBtn");

const resultBadge = document.getElementById("resultBadge");
const resultStatusText = document.getElementById("resultStatusText");
const resultFileName = document.getElementById("resultFileName");
const resultFileSize = document.getElementById("resultFileSize");
const resultInputFormat = document.getElementById("resultInputFormat");
const resultOutputFormat = document.getElementById("resultOutputFormat");
const resultOutputName = document.getElementById("resultOutputName");
const resultShape = document.getElementById("resultShape");
const resultDtype = document.getElementById("resultDtype");
const resultNdim = document.getElementById("resultNdim");
const resultAxisKeys = document.getElementById("resultAxisKeys");
const resultPath = document.getElementById("resultPath");

// Optional nodes: current converter2.html may omit these.
// Keep graceful support so the same app.js can work if they are added later.
const resultEp = document.getElementById("resultEp");
const resultHv = document.getElementById("resultHv");
const resultTemperature = document.getElementById("resultTemperature");
const resultPolarization = document.getElementById("resultPolarization");
const resultMetadataMode = document.getElementById("resultMetadataMode");
const resultExtraFields = document.getElementById("resultExtraFields");

let selectedFile = null;
let currentObjectUrl = null;
let pyodide = null;
let pyReady = false;

const extensionMap = {
  ibw: "ibw",
  itx: "itx",
  pxt: "pxt",
  npz: "npz",
  xarray: "nc",
  da30_zip: "zip",
  tof_folder: "zip"
};

const supportedPaths = new Set([
  "ibw->npz",
  "npz->ibw",
  "itx->npz",
  "npz->itx",
  "pxt->npz",
  "da30_zip->npz",
  "npz->xarray",
  "xarray->npz"
]);

function setText(el, value) {
  if (!el) return;
  el.textContent = value;
}

function titleCaseStatus(value) {
  const map = {
    idle: "Idle",
    ready: "Ready",
    running: "Running",
    success: "Success",
    error: "Error"
  };
  return map[value] || value;
}

function updateResultStatus(status, message) {
  setText(resultBadge, titleCaseStatus(status));
  setText(resultStatusText, message || "");
}

function setResultValue(el, value, fallback = "—") {
  if (!el) return;
  const text = value === undefined || value === null || value === "" ? fallback : String(value);
  el.textContent = text;
}

function resetResultSummary() {
  setResultValue(resultFileName, "—");
  setResultValue(resultFileSize, "—");
  setResultValue(resultInputFormat, "—");
  setResultValue(resultOutputFormat, "—");
  setResultValue(resultOutputName, "—");
  setResultValue(resultShape, "—");
  setResultValue(resultDtype, "—");
  setResultValue(resultNdim, "—");
  setResultValue(resultAxisKeys, "—");
  setResultValue(resultPath, "—");

  setResultValue(resultEp, "—");
  setResultValue(resultHv, "—");
  setResultValue(resultTemperature, "—");
  setResultValue(resultPolarization, "—");
  setResultValue(resultMetadataMode, "—");
  setResultValue(resultExtraFields, "—");
}

function updateSelectedFileSummary(file) {
  const { inputFormat, outputFormat } = getSelectedFormats();
  setResultValue(resultFileName, file?.name || "—");
  setResultValue(resultFileSize, file ? formatBytes(file.size) : "—");
  setResultValue(resultInputFormat, inputFormat ? inputFormat.toUpperCase() : "—");
  setResultValue(resultOutputFormat, outputFormat ? outputFormat.toUpperCase() : "—");
  setResultValue(resultPath, getCurrentPathKey() || "—");
}

function updateOutputSummaryFromPythonMeta(meta, outputFilename) {
  const shape = Array.isArray(meta?.shape) ? `[${meta.shape.join(", ")}]` : "—";
  const axisKeys = Array.isArray(meta?.axis_keys) && meta.axis_keys.length
    ? meta.axis_keys.join(", ")
    : "—";

  setResultValue(resultOutputName, outputFilename || "—");
  setResultValue(resultShape, shape);
  setResultValue(resultDtype, meta?.dtype || "—");
  setResultValue(resultNdim, meta?.ndim ?? "—");
  setResultValue(resultAxisKeys, axisKeys);
}

function updateMetadataSummary(options, pythonMeta) {
  const customKeys = Object.keys(options?.custom_metadata || {});
  setResultValue(resultEp, options?.Ep);
  setResultValue(resultHv, options?.hv);
  setResultValue(resultTemperature, options?.temperature_K);
  setResultValue(resultPolarization, options?.polarization);
  setResultValue(resultMetadataMode, options?.metadata_mode || "preserve");
  setResultValue(
    resultExtraFields,
    customKeys.length ? customKeys.join(", ") : (pythonMeta?.extra_metadata_keys || "—")
  );
}

function setLog(message, replace = false) {
  if (!logBox) return;
  if (replace) {
    logBox.textContent = message;
    return;
  }
  const current = logBox.textContent.trim();
  logBox.textContent = current ? `${current}\n${message}` : message;
}

function setMeta(data) {
  if (!metaBox) return;
  metaBox.textContent = JSON.stringify(data, null, 2);
}

function clearDownloadLink() {
  if (!downloadLink) return;

  downloadLink.hidden = true;
  downloadLink.removeAttribute("href");
  downloadLink.removeAttribute("download");

  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl);
    currentObjectUrl = null;
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unitIndex]}`;
}

function parseCommaSeparatedList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function getSelectedFormats() {
  return {
    inputFormat: inputFormatSelect?.value || "",
    outputFormat: outputFormatSelect?.value || ""
  };
}

function getCurrentPathKey() {
  const { inputFormat, outputFormat } = getSelectedFormats();
  return `${inputFormat}->${outputFormat}`;
}

function isSupportedPath() {
  return supportedPaths.has(getCurrentPathKey());
}

function inferExtensionForFormat(format) {
  const extensionMap = {
    ibw: "ibw",
    itx: "itx",
    pxt: "pxt",
    npz: "npz",
    xarray: "nc",
    da30_zip: "zip",
    tof_folder: "zip"
};
  return extensionMap[format] || "dat";
}

function buildOutputFilename(inputFilename, outputFormat) {
  const customName = outputNameInput?.value?.trim();
  const ext = inferExtensionForFormat(outputFormat);
  const { inputFormat } = getSelectedFormats();

  if (customName) {
    return customName.includes(".") ? customName : `${customName}.${ext}`;
  }

  return `${inputFormat}_to_${outputFormat}.${ext}`;
}

function sanitizeMetadataKey(value) {
  return (value || "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-zA-Z0-9_\-]/g, "");
}

function getTextValue(element) {
  return element?.value?.trim?.() || "";
}

function getRawValue(element) {
  return element?.value ?? "";
}

function getNumericValue(element) {
  const raw = element?.value;
  if (raw === undefined || raw === null || raw === "") return "";
  const parsed = Number(raw);
  return Number.isNaN(parsed) ? raw : parsed;
}

function createCustomMetadataValueInput(type = "text", value = "") {
  let inputEl;

  if (type === "number") {
    inputEl = document.createElement("input");
    inputEl.type = "number";
    inputEl.step = "any";
  } else if (type === "date") {
    inputEl = document.createElement("input");
    inputEl.type = "date";
  } else if (type === "datetime") {
    inputEl = document.createElement("input");
    inputEl.type = "datetime-local";
  } else if (type === "boolean") {
    inputEl = document.createElement("select");
    inputEl.innerHTML = `
      <option value="true">true</option>
      <option value="false">false</option>
    `;
  } else {
    inputEl = document.createElement("input");
    inputEl.type = "text";
    inputEl.placeholder = "Value";
  }

  inputEl.className = "custom-metadata-value";
  inputEl.value = value ?? "";
  return inputEl;
}

function refreshSelectedFileMetaPreview() {
  if (!selectedFile) return;

  const options = collectOptions();
  updateSelectedFileSummary(selectedFile);
  updateMetadataSummary(options, null);

  setMeta({
    status: "file_selected",
    filename: selectedFile.name,
    size_bytes: selectedFile.size,
    input_format: getSelectedFormats().inputFormat,
    output_format: getSelectedFormats().outputFormat,
    supported_path: isSupportedPath(),
    pyodide_ready: pyReady,
    options_preview: options
  });
}

function addCustomMetadataField(key = "", type = "text", value = "") {
  if (!customMetadataList) return;

  const row = document.createElement("div");
  row.className = "custom-metadata-row form-grid";

  const keyGroup = document.createElement("div");
  keyGroup.className = "form-group";
  const keyInput = document.createElement("input");
  keyInput.type = "text";
  keyInput.className = "custom-metadata-key";
  keyInput.placeholder = "Key";
  keyInput.value = key;
  keyGroup.appendChild(keyInput);

  const typeGroup = document.createElement("div");
  typeGroup.className = "form-group";
  const typeSelect = document.createElement("select");
  typeSelect.className = "custom-metadata-type";
  typeSelect.innerHTML = `
    <option value="text">Text</option>
    <option value="number">Number</option>
    <option value="date">Date</option>
    <option value="datetime">DateTime</option>
    <option value="boolean">Boolean</option>
  `;
  typeSelect.value = type;
  typeGroup.appendChild(typeSelect);

  const valueGroup = document.createElement("div");
  valueGroup.className = "form-group";
  let valueInput = createCustomMetadataValueInput(type, value);
  valueGroup.appendChild(valueInput);

  const actionGroup = document.createElement("div");
  actionGroup.className = "form-group";
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "button button-secondary";
  removeBtn.textContent = "Remove";
  removeBtn.addEventListener("click", () => {
    row.remove();
    refreshSelectedFileMetaPreview();
  });
  actionGroup.appendChild(removeBtn);

  typeSelect.addEventListener("change", () => {
    const oldValue = valueInput?.value ?? "";
    const nextInput = createCustomMetadataValueInput(typeSelect.value, oldValue);
    valueGroup.replaceChild(nextInput, valueInput);
    valueInput = nextInput;
    refreshSelectedFileMetaPreview();
  });

  row.appendChild(keyGroup);
  row.appendChild(typeGroup);
  row.appendChild(valueGroup);
  row.appendChild(actionGroup);
  customMetadataList.appendChild(row);
}

function parseCustomMetadataValue(type, rawValue) {
  if (rawValue === "") return "";

  if (type === "number") {
    const parsed = Number(rawValue);
    return Number.isNaN(parsed) ? rawValue : parsed;
  }

  if (type === "boolean") {
    return rawValue === "true";
  }

  return rawValue;
}

function collectCustomMetadata() {
  const result = {};
  if (!customMetadataList) return result;

  const rows = customMetadataList.querySelectorAll(".custom-metadata-row");
  rows.forEach((row) => {
    const keyEl = row.querySelector(".custom-metadata-key");
    const typeEl = row.querySelector(".custom-metadata-type");
    const valueEl = row.querySelector(".custom-metadata-value");

    const key = sanitizeMetadataKey(keyEl?.value || "");
    const type = typeEl?.value || "text";
    const rawValue = valueEl?.value ?? "";

    if (!key) return;
    result[key] = parseCustomMetadataValue(type, rawValue);
  });

  return result;
}

function collectOptions() {
  return {
    axis_labels: parseCommaSeparatedList(getRawValue(axisLabelsInput)),
    axis_units: parseCommaSeparatedList(getRawValue(axisUnitsInput)),
    experiment_date: getRawValue(experimentDateInput),
    sample_name: getTextValue(sampleNameInput),
    operator: getTextValue(operatorInput),
    location: getTextValue(locationInput),
    hv: getNumericValue(hvInput),
    slit: getTextValue(slitInput),
    temperature_K: getNumericValue(temperatureInput),
    polarization: getRawValue(polarizationInput),
    notes: getTextValue(notesInput),
    metadata_mode: getRawValue(metadataModeSelect) || "preserve",
    output_name: getTextValue(outputNameInput),
    custom_metadata: collectCustomMetadata()
  };
}

function updatePathStatus() {
  const { inputFormat, outputFormat } = getSelectedFormats();
  const pathKey = getCurrentPathKey();

  clearDownloadLink();
  updateSelectedFileSummary(selectedFile);

  if (inputFormat === outputFormat) {
    updateResultStatus("error", "Input and output formats must be different.");
    setLog("Input and output formats are identical. Please choose a different output format.", true);
    setMeta({
      ready: false,
      reason: "Input and output formats must be different.",
      input_format: inputFormat,
      output_format: outputFormat,
      pyodide_ready: pyReady
    });
    return;
  }

  if (isSupportedPath()) {
    updateResultStatus(
      selectedFile ? "ready" : "idle",
      selectedFile
        ? `Ready to convert via ${inputFormat.toUpperCase()} → ${outputFormat.toUpperCase()}.`
        : "Choose a file and click Convert."
    );
    setLog(`Ready. Selected path: ${inputFormat} → ${outputFormat}`, false);
    setMeta({
      ready: true,
      supported_path: true,
      selected_path: pathKey,
      pyodide_ready: pyReady
    });
  } else {
    updateResultStatus("error", `This path is planned but not enabled: ${inputFormat.toUpperCase()} → ${outputFormat.toUpperCase()}.`);
    setLog(`Selected path is not yet enabled: ${inputFormat} → ${outputFormat}`, true);
    setMeta({
      ready: false,
      supported_path: false,
      selected_path: pathKey,
      pyodide_ready: pyReady,
      message: "This conversion path is planned but not enabled in the current prototype."
    });
  }
}

function setSelectedFile(file) {
  selectedFile = file || null;
  clearDownloadLink();
  updateSelectedFileSummary(selectedFile);

  if (!selectedFile) {
    resetResultSummary();
    updateResultStatus(pyReady ? "idle" : "running", pyReady ? "Choose a file and click Convert." : "Python runtime is still loading...");
    setLog(pyReady ? "Ready." : "Python runtime is still loading...", true);
    setMeta({ status: "idle", pyodide_ready: pyReady });
    return;
  }

  if (selectedFile.size > HARD_LIMIT_BYTES) {
    updateResultStatus("error", "Selected file exceeds the 1 GB hard limit.");
    setLog("Selected file exceeds the 1 GB hard limit for this tool.", true);
    setMeta({
        ready: false,
        status: "file_too_large",
        filename: selectedFile.name,
        size_bytes: selectedFile.size,
        limit_bytes: HARD_LIMIT_BYTES,
        pyodide_ready: pyReady
    });
    return;
    }

    if (selectedFile.size > RECOMMENDED_SIZE_BYTES) {
    updateResultStatus("ready", "File selected. Files larger than 100 MB may be slower in the browser.");
    setLog("File selected. Warning: files above 100 MB may be slower in the browser.", true);
    } else {
    updateResultStatus("ready", "File selected. Review formats and click Convert.");
    setLog("File selected.", true);
    }

  const { inputFormat, outputFormat } = getSelectedFormats();
  const options = collectOptions();

  updateMetadataSummary(options, null);

  setMeta({
    status: "file_selected",
    filename: selectedFile.name,
    size_bytes: selectedFile.size,
    input_format: inputFormat,
    output_format: outputFormat,
    supported_path: isSupportedPath(),
    pyodide_ready: pyReady,
    options_preview: options
  });
}

async function initPyodideRuntime() {
  try {
    updateResultStatus("running", "Loading Python runtime...");
    setLog("Loading Python runtime...", true);

    pyodide = await loadPyodide();

    setLog("Loading Python packages...");
    await pyodide.loadPackage(["numpy", "xarray", "scipy"]);

    setLog("Loading converter.py...");
    const response = await fetch(`./py/converter.py?v=${Date.now()}`);
    if (!response.ok) {
      throw new Error(`Failed to load converter.py (${response.status})`);
    }

    const pythonSource = await response.text();
    pyodide.runPython(pythonSource);

    pyReady = true;
    setLog("Python ready.", true);

    setMeta({
      status: "python_ready",
      pyodide_ready: true
    });

    updatePathStatus();
    if (selectedFile) {
      handlePreview(selectedFile);
    }
  } catch (error) {
    pyReady = false;
    updateResultStatus("error", `Pyodide initialization failed: ${error.message}`);
    setLog(`Pyodide initialization failed: ${error.message}`, true);
    setMeta({
      status: "pyodide_init_error",
      pyodide_ready: false,
      error: error.message
    });
    console.error(error);
  }
}

async function callPythonConverter(fileBytes, inputFormat, outputFormat, options) {
  if (!pyodide) {
    throw new Error("Pyodide is not initialized.");
  }

  pyodide.globals.set("js_input_bytes", fileBytes);
  pyodide.globals.set("js_input_format", inputFormat);
  pyodide.globals.set("js_output_format", outputFormat);
  pyodide.globals.set("js_options", options);

  await pyodide.runPythonAsync(`
_input_bytes = bytes(js_input_bytes.to_py())
_input_format = str(js_input_format)
_output_format = str(js_output_format)
_options = js_options.to_py()

_output_bytes, _meta = convert_bytes(
    _input_bytes,
    _input_format,
    _output_format,
    _options
)
`);

  const pyOutputBytes = pyodide.globals.get("_output_bytes");
  const pyMeta = pyodide.globals.get("_meta");

  let outputBytes;
  if (pyOutputBytes.toJs) {
    outputBytes = pyOutputBytes.toJs();
  } else {
    outputBytes = pyOutputBytes;
  }

  let meta;
  if (pyMeta.toJs) {
    meta = pyMeta.toJs({ dict_converter: Object.fromEntries });
  } else {
    meta = pyMeta;
  }

  pyOutputBytes.destroy?.();
  pyMeta.destroy?.();

  pyodide.globals.delete("js_input_bytes");
  pyodide.globals.delete("js_input_format");
  pyodide.globals.delete("js_output_format");
  pyodide.globals.delete("js_options");
  pyodide.globals.delete("_output_bytes");
  pyodide.globals.delete("_meta");

  return { outputBytes, meta };
}

async function handleConvert() {
  clearDownloadLink();

  const { inputFormat, outputFormat } = getSelectedFormats();

  if (!selectedFile) {
    updateResultStatus("error", "Please select a file first.");
    setLog("Please select a file first.", true);
    setMeta({
      status: "error",
      reason: "No file selected.",
      pyodide_ready: pyReady
    });
    return;
  }

  if (!pyReady) {
    updateResultStatus("error", "Python runtime is not ready yet.");
    setLog("Python runtime is not ready yet.", true);
    setMeta({
      status: "error",
      reason: "Pyodide is still initializing.",
      pyodide_ready: pyReady
    });
    return;
  }

  if (selectedFile.size > HARD_LIMIT_BYTES) {
    updateResultStatus("error", "Conversion blocked: file is larger than 1 GB.");
    setLog("Conversion blocked: file is larger than 1 GB.", true);
    setMeta({
        status: "error",
        reason: "File too large.",
        limit_bytes: HARD_LIMIT_BYTES,
        pyodide_ready: pyReady
    });
    return;
    }

  if (inputFormat === outputFormat) {
    updateResultStatus("error", "Please choose different input and output formats.");
    setLog("Please choose different input and output formats.", true);
    setMeta({
      status: "error",
      reason: "Input and output formats are identical.",
      pyodide_ready: pyReady
    });
    return;
  }

  if (!isSupportedPath()) {
    updateResultStatus("error", `Path not enabled yet: ${inputFormat.toUpperCase()} → ${outputFormat.toUpperCase()}.`);
    setLog(`Path not enabled yet: ${inputFormat} → ${outputFormat}`, true);
    setMeta({
      status: "error",
      reason: "Unsupported path in current prototype.",
      selected_path: `${inputFormat}->${outputFormat}`,
      pyodide_ready: pyReady
    });
    return;
  }

  const options = collectOptions();
  updateMetadataSummary(options, null);

  updateResultStatus("running", "Preparing conversion...");
  setLog("Preparing conversion...", true);
  setMeta({
    status: "running",
    filename: selectedFile.name,
    size_bytes: selectedFile.size,
    input_format: inputFormat,
    output_format: outputFormat,
    pyodide_ready: pyReady,
    options
  });

  try {
    setLog("Reading file bytes...");
    const arrayBuffer = await selectedFile.arrayBuffer();
    const fileBytes = new Uint8Array(arrayBuffer);

    setLog("Calling Python converter...");
    const { outputBytes, meta } = await callPythonConverter(
    fileBytes,
    inputFormat,
    outputFormat,
    options
    );

    if (!meta || meta.success !== true) {
    const msg = meta?.error_message || meta?.message || "Conversion failed.";
    throw new Error(msg);
    }

    setLog("Building download file...");
    const blob = new Blob([new Uint8Array(outputBytes)], {
    type: "application/octet-stream"
    });

    const outputFilename = buildOutputFilename(selectedFile.name, outputFormat);

    currentObjectUrl = URL.createObjectURL(blob);
    if (downloadLink) {
      downloadLink.href = currentObjectUrl;
      downloadLink.download = outputFilename;
      downloadLink.hidden = false;
    }

    updateSelectedFileSummary(selectedFile);
    updateOutputSummaryFromPythonMeta(meta, outputFilename);
    updateMetadataSummary(options, meta);

    updateResultStatus("success", `Conversion complete. Output ready: ${outputFilename}`);
    setLog("Conversion complete.");

    setMeta({
      status: "complete",
      pyodide_ready: pyReady,
      filename: selectedFile.name,
      size_bytes: selectedFile.size,
      input_format: inputFormat,
      output_format: outputFormat,
      output_filename: outputFilename,
      output_blob_size: blob.size,
      python_meta: meta,
      options_used: options
    });
  } catch (error) {
    console.error(error);
    updateResultStatus("error", `Conversion failed: ${error.message}`);
    setLog(`Conversion failed: ${error.message}`, true);
    setMeta({
      status: "conversion_error",
      pyodide_ready: pyReady,
      error: error.message
    });
  }
}

function setupFileInput() {
  if (chooseFileBtn && fileInput) {
    chooseFileBtn.addEventListener("click", () => {
      fileInput.click();
    });

    fileInput.addEventListener("change", (event) => {
      const file = event.target.files?.[0] || null;
      setSelectedFile(file);
    });
  }
}

function setupDropzone() {
  if (!uploadDropzone || !fileInput) return;

  ["dragenter", "dragover"].forEach((eventName) => {
    uploadDropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadDropzone.classList.add("is-dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    uploadDropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadDropzone.classList.remove("is-dragover");
    });
  });

  uploadDropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0] || null;
    if (!file) return;

    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;

    setSelectedFile(file);
  });
}

function setupFormatSelectors() {
  [inputFormatSelect, outputFormatSelect].forEach((element) => {
    if (!element) return;
    element.addEventListener("change", updatePathStatus);
  });
}

function setupConvertButton() {
  if (!convertBtn) return;
  convertBtn.addEventListener("click", handleConvert);
}

function setupAdvancedOptionInputs() {
  [
    axisLabelsInput,
    axisUnitsInput,
    experimentDateInput,
    sampleNameInput,
    operatorInput,
    locationInput,
    hvInput,
    slitInput,
    temperatureInput,
    polarizationInput,
    notesInput,
    metadataModeSelect,
    outputNameInput
  ].forEach((element) => {
    if (!element) return;
    const eventName = element.tagName === "SELECT" ? "change" : "input";
    element.addEventListener(eventName, () => {
      refreshSelectedFileMetaPreview();
      if (selectedFile) {
        handlePreview(selectedFile);
      }
    });
  });
}

function setupCustomMetadata() {
  if (addCustomMetadataBtn) {
    addCustomMetadataBtn.addEventListener("click", () => {
      addCustomMetadataField();
      refreshSelectedFileMetaPreview();
    });
  }

  if (customMetadataList) {
    customMetadataList.addEventListener("input", () => {
      refreshSelectedFileMetaPreview();
      if (selectedFile) {
        handlePreview(selectedFile);
      }
    });
    customMetadataList.addEventListener("change", () => {
      refreshSelectedFileMetaPreview();
      if (selectedFile) {
        handlePreview(selectedFile);
      }
    });
  }
}

function init() {
  resetResultSummary();
  updateResultStatus("running", "Initializing...");
  setLog("Initializing...", true);
  setMeta({ status: "initializing", pyodide_ready: false });

  setupFileInput();
  setupDropzone();
  setupFormatSelectors();
  setupConvertButton();
  setupAdvancedOptionInputs();
  setupCustomMetadata();
  updatePathStatus();
  initPyodideRuntime();
}

document.addEventListener("DOMContentLoaded", init);



const previewWorkspace = document.getElementById("previewWorkspace");
const previewState = document.getElementById("previewState");
const previewPlotWrap = document.getElementById("previewPlotWrap");
const previewCanvas = document.getElementById("previewCanvas");
const previewViewerWrap = document.getElementById("previewViewerWrap");
const openViewerLink = document.getElementById("openViewerLink");
const replaceFileBtn = document.getElementById("replaceFileBtn");

function showUploadWorkspace() {
  if (uploadDropzone) uploadDropzone.hidden = false;
  if (previewWorkspace) previewWorkspace.hidden = true;
}

function showPreviewWorkspace() {
  if (uploadDropzone) uploadDropzone.hidden = true;
  if (previewWorkspace) previewWorkspace.hidden = false;
}

function resetPreview() {
  if (previewState) {
    previewState.textContent = "No preview yet.";
  }
  if (previewPlotWrap) {
    previewPlotWrap.hidden = true;
  }
  if (previewViewerWrap) {
    previewViewerWrap.hidden = true;
  }
  if (previewCanvas) {
    const ctx = previewCanvas.getContext("2d");
    ctx.clearRect(0, 0, previewCanvas.width || 1, previewCanvas.height || 1);
  }
  showUploadWorkspace();
}

function finiteNumberOrNull(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function normalize1DPreview(preview) {
  if (!preview) return null;
  const x = Array.isArray(preview.x) ? preview.x.map(finiteNumberOrNull).filter(v => v !== null) : null;
  const y = Array.isArray(preview.y) ? preview.y.map(finiteNumberOrNull).filter(v => v !== null) : null;

  if (y && y.length >= 2) {
    return {
      x: x && x.length === y.length ? x : y.map((_, i) => i),
      y
    };
  }

  if (Array.isArray(preview.data)) {
    const arr = preview.data.map(finiteNumberOrNull).filter(v => v !== null);
    if (arr.length >= 2) {
      return { x: arr.map((_, i) => i), y: arr };
    }
  }

  return null;
}

function draw1DPreview(preview) {
  if (!previewCanvas) return;
  const normalized = normalize1DPreview(preview);
  if (!normalized) {
    if (previewState) previewState.textContent = "1D data detected, but no usable preview vector was returned.";
    if (previewPlotWrap) previewPlotWrap.hidden = true;
    return;
  }

  const { x, y } = normalized;
  const width = 900;
  const height = 320;
  const padL = 54;
  const padR = 18;
  const padT = 20;
  const padB = 40;

  previewCanvas.width = width;
  previewCanvas.height = height;
  const ctx = previewCanvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const xMin = Math.min(...x);
  const xMax = Math.max(...x);
  const yMin = Math.min(...y);
  const yMax = Math.max(...y);
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;

  ctx.strokeStyle = "#d8dee8";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, padT);
  ctx.lineTo(padL, height - padB);
  ctx.lineTo(width - padR, height - padB);
  ctx.stroke();

  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2;
  ctx.beginPath();

  for (let i = 0; i < y.length; i += 1) {
    const px = padL + ((x[i] - xMin) / xSpan) * (width - padL - padR);
    const py = height - padB - ((y[i] - yMin) / ySpan) * (height - padT - padB);
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();

  ctx.fillStyle = "#64748b";
  ctx.font = "12px sans-serif";
  ctx.fillText(String(xMin), padL, height - 12);
  ctx.fillText(String(xMax), width - padR - 32, height - 12);
  ctx.fillText(String(yMin), 8, height - padB + 4);
  ctx.fillText(String(yMax), 8, padT + 4);

  if (previewPlotWrap) previewPlotWrap.hidden = false;
}

function normalize2DPreview(preview) {
  if (!preview) return null;
  const img = preview.image_small || preview.image || preview.data;
  if (!Array.isArray(img) || !img.length || !Array.isArray(img[0])) return null;

  const rows = img.length;
  const cols = img[0].length;
  const matrix = [];
  for (let r = 0; r < rows; r += 1) {
    const row = [];
    for (let c = 0; c < cols; c += 1) {
      const v = finiteNumberOrNull(img[r][c]);
      row.push(v === null ? 0 : v);
    }
    matrix.push(row);
  }
  return matrix;
}

function draw2DPreview(preview) {
  if (!previewCanvas) return;
  const matrix = normalize2DPreview(preview);
  if (!matrix) {
    if (previewState) previewState.textContent = "2D data detected, but no usable preview image was returned.";
    if (previewPlotWrap) previewPlotWrap.hidden = true;
    return;
  }

  const rows = matrix.length;
  const cols = matrix[0].length;

  let vMin = Infinity;
  let vMax = -Infinity;
  for (const row of matrix) {
    for (const v of row) {
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
    }
  }
  const span = vMax - vMin || 1;

  const off = document.createElement("canvas");
  off.width = cols;
  off.height = rows;
  const offCtx = off.getContext("2d");
  const imgData = offCtx.createImageData(cols, rows);

    for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
        const flippedR = rows - 1 - r;
        const idx = (r * cols + c) * 4;
        const t = Math.max(0, Math.min(1, (matrix[flippedR][c] - vMin) / span));
        const g = Math.round(t * 255);
        imgData.data[idx] = g;
        imgData.data[idx + 1] = g;
        imgData.data[idx + 2] = g;
        imgData.data[idx + 3] = 255;
    }
    }
  offCtx.putImageData(imgData, 0, 0);

  const scale = Math.min(900 / cols, 420 / rows, 4);
  previewCanvas.width = Math.max(320, Math.round(cols * scale));
  previewCanvas.height = Math.max(220, Math.round(rows * scale));

  const ctx = previewCanvas.getContext("2d");
  ctx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, previewCanvas.width, previewCanvas.height);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, previewCanvas.width, previewCanvas.height);

  if (previewPlotWrap) previewPlotWrap.hidden = false;
}

function configureViewerLink(outputFilename, meta) {
  if (!openViewerLink) return;
  try {
    sessionStorage.setItem("arpes_preview_meta", JSON.stringify({
      output_filename: outputFilename || "",
      python_meta: meta || {}
    }));
  } catch (err) {
    console.warn("Failed to cache preview metadata for viewer:", err);
  }
  openViewerLink.href = "viewer.html";
}

function renderPreviewFromMeta(meta, outputFilename) {
  if (!previewState || !previewWorkspace) return;

  const preview = meta?.preview || null;
  const ndim = Number(meta?.ndim ?? preview?.ndim ?? NaN);

  showPreviewWorkspace();
  if (previewPlotWrap) previewPlotWrap.hidden = true;
  if (previewViewerWrap) previewViewerWrap.hidden = true;

  if (ndim === 1) {
    previewState.textContent = "1D output detected. Rendering line preview.";
    draw1DPreview(preview);
    return;
  }

  if (ndim === 2) {
    previewState.textContent = "2D output detected. Rendering image preview.";
    draw2DPreview(preview);
    return;
  }

  if (ndim === 3) {
    previewState.textContent = "3D output detected. Open it in the dedicated viewer page.";
    configureViewerLink(outputFilename, meta);
    if (previewViewerWrap) previewViewerWrap.hidden = false;
    return;
  }

  previewState.textContent = "Preview is not available for this output yet.";
}

const _originalSetSelectedFile = setSelectedFile;
setSelectedFile = function(file) {
  _originalSetSelectedFile(file);
  if (!file) {
    previewRequestToken += 1;
    resetPreview();
  } else {
    handlePreview(file);
  }
};

const _originalHandleConvert = handleConvert;
handleConvert = async function() {
  await _originalHandleConvert();
};

function setupPreviewReplaceButton() {
  if (!replaceFileBtn) return;
  replaceFileBtn.addEventListener("click", () => {
    previewRequestToken += 1;
    resetPreview();
    clearDownloadLink();
    selectedFile = null;
    if (fileInput) {
      fileInput.value = "";
    }
    resetResultSummary();
    updateResultStatus(pyReady ? "idle" : "running", pyReady ? "Choose a file and click Convert." : "Python runtime is still loading...");
    setLog(pyReady ? "Ready." : "Python runtime is still loading...", true);
    setMeta({ status: "idle", pyodide_ready: pyReady });
  });
};

const _originalInit = init;
init = function() {
  _originalInit();
  resetPreview();
  setupPreviewReplaceButton();
};

const _originalUpdatePathStatus = updatePathStatus;
updatePathStatus = function() {
  _originalUpdatePathStatus();
  if (!selectedFile) {
    resetPreview();
    return;
  }
  handlePreview(selectedFile);
};

// Patch success path by wrapping setMeta after conversion would be too broad.
// Instead patch updateOutputSummaryFromPythonMeta call site via wrapping function.
const _originalUpdateOutputSummaryFromPythonMeta = updateOutputSummaryFromPythonMeta;
updateOutputSummaryFromPythonMeta = function(meta, outputFilename) {
  _originalUpdateOutputSummaryFromPythonMeta(meta, outputFilename);
  renderPreviewFromMeta(meta, outputFilename);
};



let previewRequestToken = 0;

async function callPythonPreview(fileBytes, inputFormat, options) {
  if (!pyodide) {
    throw new Error("Pyodide is not initialized.");
  }

  pyodide.globals.set("js_preview_input_bytes", fileBytes);
  pyodide.globals.set("js_preview_input_format", inputFormat);
  pyodide.globals.set("js_preview_options", options);

  await pyodide.runPythonAsync(`
_preview_input_bytes = bytes(js_preview_input_bytes.to_py())
_preview_input_format = str(js_preview_input_format)
_preview_options = js_preview_options.to_py()

_preview_meta = preview_bytes(
    _preview_input_bytes,
    _preview_input_format,
    _preview_options
)
`);

  const pyMeta = pyodide.globals.get("_preview_meta");
  let meta;
  if (pyMeta.toJs) {
    meta = pyMeta.toJs({ dict_converter: Object.fromEntries });
  } else {
    meta = pyMeta;
  }

  pyMeta.destroy?.();

  pyodide.globals.delete("js_preview_input_bytes");
  pyodide.globals.delete("js_preview_input_format");
  pyodide.globals.delete("js_preview_options");
  pyodide.globals.delete("_preview_input_bytes");
  pyodide.globals.delete("_preview_input_format");
  pyodide.globals.delete("_preview_options");
  pyodide.globals.delete("_preview_meta");

  return meta;
}

async function handlePreview(file) {
  if (!file) {
    resetPreview();
    return;
  }

  const { inputFormat } = getSelectedFormats();
  const previewableFormats = new Set(["itx", "ibw", "pxt", "npz"]);
  setLog(`Preview requested: inputFormat=${inputFormat}, pyReady=${pyReady}`, false);

  if (!pyReady) {
    showUploadWorkspace();
    if (previewState) {
      previewState.textContent = "Preview will be available after the Python runtime finishes loading.";
    }
    setLog(`Preview skipped: pyReady=${pyReady}`, false);
    return;
  }

  if (!previewableFormats.has(inputFormat)) {
    showUploadWorkspace();
    if (previewState) {
      previewState.textContent = `Preview before conversion is not available for ${inputFormat.toUpperCase()} yet.`;
    }
    setLog(`Preview skipped: inputFormat=${inputFormat}`, false);
    return;
  }

  setLog("Preview passed early checks.", false);
  const myToken = ++previewRequestToken;

  try {
    showPreviewWorkspace();
    if (previewPlotWrap) previewPlotWrap.hidden = true;
    if (previewViewerWrap) previewViewerWrap.hidden = true;
    if (previewState) {
      previewState.textContent = "Loading preview...";
    }

    setLog("Preview: reading file bytes...", false);
    const arrayBuffer = await file.arrayBuffer();

    if (myToken !== previewRequestToken) return;

    const options = collectOptions();
    const fileBytes = new Uint8Array(arrayBuffer);
    setLog("Preview: calling Python preview...", false);
    const meta = await callPythonPreview(fileBytes, inputFormat, options);

    if (myToken !== previewRequestToken) return;

    setLog(`Preview response: success=${meta?.success}, ndim=${meta?.ndim}`, false);

    if (!meta?.success) {
      showPreviewWorkspace();
      if (previewPlotWrap) previewPlotWrap.hidden = true;
      if (previewViewerWrap) previewViewerWrap.hidden = true;
      if (previewState) {
        previewState.textContent = `Preview failed: ${meta?.error_message || "Unknown error."}`;
      }
      setLog(`Preview failed: ${meta?.error_message || "Unknown error."}`, false);
      return;
    }

    renderPreviewFromMeta(meta, "");
    setLog(`Preview ready. Detected ${meta?.ndim ?? "unknown"}D input.`, false);
  } catch (error) {
    if (myToken !== previewRequestToken) return;
    showPreviewWorkspace();
    if (previewPlotWrap) previewPlotWrap.hidden = true;
    if (previewViewerWrap) previewViewerWrap.hidden = true;
    if (previewState) {
      previewState.textContent = `Preview failed: ${error.message}`;
    }
    setLog(`Preview failed: ${error.message}`, false);
  }
}
